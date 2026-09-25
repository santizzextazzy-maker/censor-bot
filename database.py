import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


class Database:
    """Небольшой слой SQLite. База хранится на постоянном диске Bothost."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self):
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                max_user_id INTEGER UNIQUE NOT NULL,
                first_name TEXT,
                username TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                max_chat_id INTEGER UNIQUE NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL DEFAULT 'PRO',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                started_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                paused_at TEXT
            );

            CREATE TABLE IF NOT EXISTS subscription_chats (
                subscription_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                PRIMARY KEY(subscription_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                plan TEXT NOT NULL DEFAULT 'PRO',
                duration_days INTEGER NOT NULL DEFAULT 30,
                status TEXT NOT NULL DEFAULT 'AVAILABLE',
                created_at TEXT NOT NULL,
                activated_at TEXT,
                activated_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS new_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                welcome_enabled INTEGER NOT NULL DEFAULT 1,
                profanity_enabled INTEGER NOT NULL DEFAULT 1,
                anti_link_enabled INTEGER NOT NULL DEFAULT 1,
                anti_spam_enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS moderation_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action TEXT NOT NULL,
                reason TEXT,
                message_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS advertisements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS advertisement_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advertisement_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );
            """)
            conn.commit()

    def upsert_user(self, user_id, first_name="", username=""):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO users(max_user_id, first_name, username, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(max_user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username
            """, (user_id, first_name, username, now))
            conn.commit()

    def upsert_chat(self, chat_id, title=""):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO chats(max_chat_id, title, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(max_chat_id) DO UPDATE SET
                    title=excluded.title,
                    active=1
            """, (chat_id, title, now))
            conn.execute("""
                INSERT OR IGNORE INTO chat_settings(chat_id)
                VALUES (?)
            """, (chat_id,))
            conn.commit()

    def remember_new_user(self, chat_id, user_id):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO new_users(chat_id, user_id, joined_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    joined_at=excluded.joined_at
            """, (chat_id, user_id, now))
            conn.commit()

    def is_new_user(self, chat_id, user_id, hours=24):
        with self.connect() as conn:
            row = conn.execute("""
                SELECT joined_at FROM new_users
                WHERE chat_id=? AND user_id=?
            """, (chat_id, user_id)).fetchone()

        if not row:
            return False

        joined = datetime.fromisoformat(row["joined_at"])
        return datetime.now(timezone.utc) - joined < timedelta(hours=hours)

    def log_action(self, chat_id, user_id, action, reason="", message_id=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO moderation_actions(
                    chat_id, user_id, action, reason, message_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, user_id, action, reason, message_id, now))
            conn.commit()

    def create_promo_codes(self, codes, plan="PRO", duration_days=30):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            for code in codes:
                conn.execute("""
                    INSERT INTO promo_codes(
                        code, plan, duration_days, status, created_at
                    ) VALUES (?, ?, ?, 'AVAILABLE', ?)
                """, (code, plan, duration_days, now))
            conn.commit()

    def activate_promo(self, code, user_id):
        now = datetime.now(timezone.utc)
        with self.connect() as conn:
            row = conn.execute("""
                SELECT * FROM promo_codes
                WHERE code=? AND status='AVAILABLE'
            """, (code,)).fetchone()

            if not row:
                return None

            expires = now + timedelta(days=int(row["duration_days"]))
            conn.execute("""
                UPDATE promo_codes
                SET status='USED', activated_at=?, activated_by=?
                WHERE id=?
            """, (now.isoformat(), user_id, row["id"]))

            # Если активная подписка уже существует, добавляем срок к ней.
            active = conn.execute("""
                SELECT * FROM subscriptions
                WHERE user_id=? AND status='ACTIVE'
                ORDER BY expires_at DESC LIMIT 1
            """, (user_id,)).fetchone()

            if active:
                old_expiry = datetime.fromisoformat(active["expires_at"])
                base = max(old_expiry, now)
                new_expiry = base + timedelta(days=int(row["duration_days"]))
                conn.execute("""
                    UPDATE subscriptions
                    SET expires_at=?, plan=?
                    WHERE id=?
                """, (new_expiry.isoformat(), row["plan"], active["id"]))
                subscription_id = active["id"]
                final_expiry = new_expiry
            else:
                conn.execute("""
                    INSERT INTO subscriptions(
                        user_id, plan, status, started_at, expires_at
                    ) VALUES (?, ?, 'ACTIVE', ?, ?)
                """, (
                    user_id,
                    row["plan"],
                    now.isoformat(),
                    expires.isoformat(),
                ))
                subscription_id = conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]
                final_expiry = expires

            conn.commit()
            return {
                "plan": row["plan"],
                "duration_days": row["duration_days"],
                "expires_at": final_expiry,
                "subscription_id": subscription_id,
            }

    def get_subscription(self, user_id):
        now = datetime.now(timezone.utc)
        with self.connect() as conn:
            row = conn.execute("""
                SELECT * FROM subscriptions
                WHERE user_id=?
                ORDER BY expires_at DESC LIMIT 1
            """, (user_id,)).fetchone()

            if row and row["status"] == "ACTIVE":
                expiry = datetime.fromisoformat(row["expires_at"])
                if expiry <= now:
                    conn.execute("""
                        UPDATE subscriptions
                        SET status='EXPIRED'
                        WHERE id=?
                    """, (row["id"],))
                    conn.commit()
                    row = dict(row)
                    row["status"] = "EXPIRED"
                    return row

            return dict(row) if row else None

    def stats(self):
        with self.connect() as conn:
            users = conn.execute(
                "SELECT COUNT(*) c FROM users"
            ).fetchone()["c"]
            chats = conn.execute(
                "SELECT COUNT(*) c FROM chats WHERE active=1"
            ).fetchone()["c"]
            active = conn.execute("""
                SELECT COUNT(*) c FROM subscriptions
                WHERE status='ACTIVE'
            """).fetchone()["c"]
            promos = conn.execute("""
                SELECT COUNT(*) c FROM promo_codes
                WHERE status='AVAILABLE'
            """).fetchone()["c"]
            actions = conn.execute(
                "SELECT COUNT(*) c FROM moderation_actions"
            ).fetchone()["c"]

        return {
            "users": users,
            "chats": chats,
            "active_subscriptions": active,
            "available_promos": promos,
            "moderation_actions": actions,
        }


def create_database(path: str):
    return Database(path)


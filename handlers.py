import logging
import re
import secrets
import string
from datetime import datetime, timezone

from maxapi.types import (
    BotAdded,
    BotRemoved,
    BotStarted,
    CallbackButton,
    Command,
    MessageCallback,
    MessageCreated,
    UserAdded,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

logger = logging.getLogger("censor_bot.handlers")

# Стартовый список. Заполняй его своими словами перед боевым запуском.
BAD_WORDS = {
    # "слово1",
    # "слово2",
}

URL_RE = re.compile(
    r"(?i)(https?://\S+|www\.\S+|\b[a-z0-9.-]+\.(ru|рф|com|net|org|info|biz|xyz|me|io)\b)"
)


def now():
    return datetime.now(timezone.utc)


def generate_code():
    alphabet = string.ascii_uppercase + string.digits
    a = "".join(secrets.choice(alphabet) for _ in range(6))
    b = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"CENSOR-{a}-{b}"


def user_name(user):
    return getattr(user, "first_name", None) or getattr(user, "name", None) or "пользователь"


def main_keyboard(is_admin=False):
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text="🎟 Активировать промокод", payload="user:activate"),
        CallbackButton(text="💎 Моя подписка", payload="user:subscription"),
    )
    kb.row(
        CallbackButton(text="📋 Помощь", payload="user:help"),
        CallbackButton(text="🆔 Мой ID", payload="user:myid"),
    )
    if is_admin:
        kb.row(
            CallbackButton(text="🛠 Админ-панель", payload="admin:home"),
        )
    return kb.as_markup()


def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text="📊 Обзор", payload="admin:stats"),
        CallbackButton(text="👥 Пользователи", payload="admin:users"),
    )
    kb.row(
        CallbackButton(text="🎟 Промокоды", payload="admin:promos"),
        CallbackButton(text="💎 Подписки", payload="admin:subscriptions"),
    )
    kb.row(
        CallbackButton(text="💬 Чаты", payload="admin:chats"),
        CallbackButton(text="📋 Журнал", payload="admin:log"),
    )
    kb.row(
        CallbackButton(text="📢 Реклама", payload="admin:ads"),
    )
    kb.row(
        CallbackButton(text="◀️ Главное меню", payload="user:home"),
    )
    return kb.as_markup()


def back_admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="◀️ Назад", payload="admin:home"))
    return kb.as_markup()


def register_handlers(dp, bot, db, settings):

    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        user = await event.fetch_from_user()
        if user:
            db.upsert_user(
                user.user_id,
                getattr(user, "first_name", ""),
                getattr(user, "username", ""),
            )
            is_admin = user.user_id in settings.admin_user_ids
        else:
            is_admin = False

        await event.bot.send_message(
            chat_id=event.chat_id,
            text=(
                "👋 Добро пожаловать в Censor BOT!\n\n"
                "Это первая версия системы. Здесь уже подготовлены "
                "кнопочное меню, подписки, промокоды и основа модерации."
            ),
            attachments=[main_keyboard(is_admin)],
        )

    @dp.message_created(Command("start"))
    async def on_start(event: MessageCreated):
        user = await event.fetch_from_user()
        if not user:
            return

        db.upsert_user(
            user.user_id,
            getattr(user, "first_name", ""),
            getattr(user, "username", ""),
        )
        is_admin = user.user_id in settings.admin_user_ids

        await event.message.answer(
            "🤖 Censor BOT\n\nВыберите нужный раздел:",
            attachments=[main_keyboard(is_admin)],
        )

    @dp.message_created(Command("myid"))
    async def on_myid(event: MessageCreated):
        user = await event.fetch_from_user()
        if not user:
            return
        db.upsert_user(
            user.user_id,
            getattr(user, "first_name", ""),
            getattr(user, "username", ""),
        )
        await event.message.answer(
            f"🆔 Ваш MAX ID:\n\n<b>{user.user_id}</b>\n\n"
            "Этот ID нужен владельцу бота для доступа к админ-панели."
        )

    @dp.message_created(Command("admin"))
    async def on_admin(event: MessageCreated):
        user = await event.fetch_from_user()
        if not user:
            return
        if user.user_id not in settings.admin_user_ids:
            await event.message.answer("⛔ Доступ запрещён.")
            return

        await event.message.answer(
            "🛠 CENSOR ADMIN\n\nВыберите раздел:",
            attachments=[admin_keyboard()],
        )

    @dp.message_created(Command("activate"))
    async def on_activate_command(event: MessageCreated):
        user = await event.fetch_from_user()
        if not user:
            return

        text = getattr(event.message.body, "text", "") or ""
        parts = text.split(maxsplit=1)

        if len(parts) != 2:
            await event.message.answer(
                "🎟 Для активации отправьте:\n"
                "<b>/activate CENSOR-XXXXXX-XXXXXX</b>"
            )
            return

        result = db.activate_promo(parts[1].strip().upper(), user.user_id)
        if not result:
            await event.message.answer(
                "❌ Промокод не найден, уже использован или недействителен."
            )
            return

        expiry = result["expires_at"].astimezone().strftime("%d.%m.%Y %H:%M")
        await event.message.answer(
            "✅ Промокод активирован!\n\n"
            f"Тариф: 💎 {result['plan']}\n"
            f"Срок: {result['duration_days']} дней\n"
            f"Действует до: <b>{expiry}</b>"
        )

    @dp.message_callback()
    async def on_callback(event: MessageCallback):
        user = await event.fetch_from_user()
        if not user:
            return

        db.upsert_user(
            user.user_id,
            getattr(user, "first_name", ""),
            getattr(user, "username", ""),
        )

        payload = event.callback.payload or ""

        # Подтверждаем callback, чтобы у пользователя не висел индикатор.
        try:
            await event.bot.send_callback(
                callback_id=event.callback.callback_id,
                notification="Готово",
            )
        except Exception:
            logger.exception("Не удалось подтвердить callback.")

        if payload == "user:home":
            await event.message.answer(
                "🤖 Censor BOT\n\nВыберите раздел:",
                attachments=[main_keyboard(user.user_id in settings.admin_user_ids)],
            )
            return

        if payload == "user:myid":
            await event.message.answer(
                f"🆔 Ваш MAX ID: <b>{user.user_id}</b>"
            )
            return

        if payload == "user:help":
            await event.message.answer(
                "📋 Помощь\n\n"
                "/start — главное меню\n"
                "/myid — ваш MAX ID\n"
                "/activate КОД — активировать промокод\n"
                "/admin — админ-панель (только владелец)\n\n"
                "В дальнейшем сюда добавим полную справку."
            )
            return

        if payload == "user:activate":
            await event.message.answer(
                "🎟 Активация промокода\n\n"
                "Отправьте отдельным сообщением:\n"
                "<b>/activate CENSOR-XXXXXX-XXXXXX</b>"
            )
            return

        if payload == "user:subscription":
            sub = db.get_subscription(user.user_id)
            if not sub:
                await event.message.answer(
                    "💎 Подписка\n\nУ вас пока нет активной подписки."
                )
                return

            expiry = datetime.fromisoformat(sub["expires_at"]).astimezone()
            status = sub["status"]
            await event.message.answer(
                "💎 Моя подписка\n\n"
                f"Тариф: {sub['plan']}\n"
                f"Статус: {'🟢 Активна' if status == 'ACTIVE' else '⛔ Истекла'}\n"
                f"До: {expiry.strftime('%d.%m.%Y %H:%M')}"
            )
            return

        if payload.startswith("admin:"):
            if user.user_id not in settings.admin_user_ids:
                await event.message.answer("⛔ Доступ запрещён.")
                return

            if payload == "admin:home":
                await event.message.answer(
                    "🛠 CENSOR ADMIN\n\nВыберите раздел:",
                    attachments=[admin_keyboard()],
                )
                return

            if payload == "admin:stats":
                s = db.stats()
                await event.message.answer(
                    "📊 ОБЗОР\n\n"
                    f"👥 Пользователей: {s['users']}\n"
                    f"💬 Чатов: {s['chats']}\n"
                    f"💎 Активных подписок: {s['active_subscriptions']}\n"
                    f"🎟 Свободных промокодов: {s['available_promos']}\n"
                    f"🛡 Действий модерации: {s['moderation_actions']}",
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:promos":
                codes = [generate_code() for _ in range(1)]
                await event.message.answer(
                    "🎟 ПРОМОКОДЫ\n\n"
                    "Для безопасности массовое создание кодов будет "
                    "добавлено отдельным мастером.\n\n"
                    "Кнопочная структура уже подготовлена."
                    "\n\nДоступные действия будут: создать, список, "
                    "поиск, история."
                    "\n\nПример кода: " + codes[0],
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:subscriptions":
                await event.message.answer(
                    "💎 ПОДПИСКИ\n\n"
                    "Здесь будет управление активными, приостановленными "
                    "и истёкшими подписками.",
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:users":
                await event.message.answer(
                    "👥 ПОЛЬЗОВАТЕЛИ\n\n"
                    "Раздел поиска и управления пользователями подготовлен "
                    "в архитектуре БД.",
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:chats":
                await event.message.answer(
                    "💬 ЧАТЫ\n\n"
                    "Здесь будут активные чаты, тарифы, настройки и "
                    "статистика каждого чата.",
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:log":
                await event.message.answer(
                    "📋 ЖУРНАЛ\n\n"
                    "Все действия модерации записываются в SQLite."
                    "\n\nПолноценный просмотр с пагинацией добавим следующим "
                    "этапом.",
                    attachments=[back_admin_keyboard()],
                )
                return

            if payload == "admin:ads":
                if not settings.free_ad_enabled:
                    await event.message.answer(
                        "📢 РЕКЛАМА\n\nМодуль отключён настройкой FREE_AD_ENABLED."
                    )
                else:
                    await event.message.answer(
                        "📢 РЕКЛАМА\n\n"
                        "Здесь будет создание объявления, разовая рассылка, "
                        "планирование, аудитория бесплатных чатов и статистика.",
                        attachments=[back_admin_keyboard()],
                    )
                return

    @dp.bot_added()
    async def on_bot_added(event: BotAdded):
        chat = await event.fetch_chat()
        chat_id = event.chat_id
        title = getattr(chat, "title", "") if chat else ""
        db.upsert_chat(chat_id, title)

        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "🛡 Censor BOT подключён!\n\n"
                "Для корректной работы модерации выдайте боту права "
                "администратора, включая удаление сообщений.\n\n"
                "В личном чате доступно меню настройки."
            ),
        )
        logger.info("Бот добавлен в чат: %s (%s)", chat_id, title)

    @dp.bot_removed()
    async def on_bot_removed(event: BotRemoved):
        logger.info("Бот удалён из чата: %s", event.chat_id)
        with db.connect() as conn:
            conn.execute(
                "UPDATE chats SET active=0 WHERE max_chat_id=?",
                (event.chat_id,),
            )
            conn.commit()

    @dp.user_added()
    async def on_user_added(event: UserAdded):
        user = await event.fetch_from_user()
        chat = await event.fetch_chat()

        if not user:
            return

        chat_id = event.chat_id
        title = getattr(chat, "title", "") if chat else ""
        db.upsert_user(
            user.user_id,
            getattr(user, "first_name", ""),
            getattr(user, "username", ""),
        )
        db.upsert_chat(chat_id, title)
        db.remember_new_user(chat_id, user.user_id)

        try:
            await event.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"👋 Добро пожаловать, {user_name(user)}!\n\n"
                    "Пожалуйста, ознакомьтесь с правилами чата."
                ),
            )
        except Exception:
            logger.exception("Не удалось отправить приветствие.")

    @dp.message_created()
    async def moderate_message(event: MessageCreated):
        """
        Базовая модерация.
        Важно: обработчик /start и /myid выше срабатывает раньше.
        """
        message = event.message
        text = getattr(message.body, "text", "") or ""
        if not text:
            return

        user = await event.fetch_from_user()
        chat = await event.fetch_chat()

        if not user or not chat:
            return

        chat_id = chat.chat_id
        user_id = user.user_id

        db.upsert_user(
            user_id,
            getattr(user, "first_name", ""),
            getattr(user, "username", ""),
        )
        db.upsert_chat(chat_id, getattr(chat, "title", ""))

        normalized = " ".join(text.lower().split())

        # Мат.
        for word in BAD_WORDS:
            if word.lower() in normalized:
                try:
                    await message.delete()
                    db.log_action(
                        chat_id,
                        user_id,
                        "DELETE",
                        f"Запрещённое слово: {word}",
                        getattr(message.body, "mid", None),
                    )
                    logger.warning(
                        "Удалено сообщение: chat=%s user=%s reason=bad_word",
                        chat_id,
                        user_id,
                    )
                except Exception:
                    logger.exception(
                        "Не удалось удалить сообщение. "
                        "Проверьте права администратора."
                    )
                return

        # Ссылки от новых участников.
        if (
            URL_RE.search(text)
            and db.is_new_user(
                chat_id,
                user_id,
                settings.new_user_protection_hours,
            )
        ):
            try:
                await message.delete()
                db.log_action(
                    chat_id,
                    user_id,
                    "DELETE",
                    "Ссылка от нового участника",
                    getattr(message.body, "mid", None),
                )
                logger.warning(
                    "Удалена ссылка новичка: chat=%s user=%s",
                    chat_id,
                    user_id,
                )
            except Exception:
                logger.exception(
                    "Не удалось удалить ссылку новичка. "
                    "Проверьте права администратора."
                )

    logger.info("Обработчики Censor BOT зарегистрированы.")

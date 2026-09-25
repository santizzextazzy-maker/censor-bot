import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_user_ids: set[int]
    webhook_url: str
    webhook_secret: str
    port: int
    database_path: str
    log_level: str
    new_user_protection_hours: int
    free_ad_enabled: bool


def _int_set(value: str) -> set[int]:
    result = set()
    for item in value.split(","):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN.")


settings = Settings(
    bot_token=BOT_TOKEN,
    admin_user_ids=_int_set(os.getenv("ADMIN_USER_IDS", "")),
    webhook_url=os.getenv("WEBHOOK_URL", "").strip().rstrip("/"),
    webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
    port=int(os.getenv("PORT", "8080")),
    database_path=os.getenv("DATABASE_PATH", "/app/data/censor.db"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    new_user_protection_hours=int(
        os.getenv("NEW_USER_PROTECTION_HOURS", "24")
    ),
    free_ad_enabled=os.getenv("FREE_AD_ENABLED", "true").lower() == "true",
)

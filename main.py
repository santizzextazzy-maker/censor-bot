import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.enums.update import UpdateType

from config import settings
from database import create_database
from handlers import register_handlers

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("censor_bot")

bot = Bot(settings.bot_token)
dp = Dispatcher()

register_handlers(dp, bot, db, settings)


async def main():
    db = await create_database(settings.database_path) 
    await db.init()

    if settings.webhook_url:
        update_types = [
            UpdateType.MESSAGE_CREATED,
            UpdateType.MESSAGE_CALLBACK,
            UpdateType.BOT_STARTED,
            UpdateType.BOT_ADDED,
            UpdateType.BOT_REMOVED,
            UpdateType.USER_ADDED,
            UpdateType.USER_REMOVED,
        ]
        try:
            await bot.subscribe_webhook(
                url=settings.webhook_url,
                update_types=update_types,
                secret=settings.webhook_secret or None,
            )
            logger.info("Webhook подписан: %s", settings.webhook_url)
        except Exception:
            logger.exception("Не удалось зарегистрировать Webhook.")
            raise
    else:
        logger.warning(
            "WEBHOOK_URL не задан. Сервер запустится, но подписка Webhook "
            "не будет создана автоматически."
        )

    logger.info("Censor BOT запускается.")
    await dp.handle_webhook(
        bot=bot,
        host="0.0.0.0",
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    asyncio.run(main())

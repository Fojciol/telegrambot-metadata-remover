import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings
from src.handlers import router, WhitelistMiddleware


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


async def main():
    setup_logging()
    logger = logging.getLogger("telegram_bot")

    try:
        settings = get_settings()
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        logger.error("Make sure BOT_TOKEN is set in your environment or .env file.")
        sys.exit(1)

    if not settings.bot_token or settings.bot_token.strip() == "":
        logger.error("BOT_TOKEN is empty! Please set BOT_TOKEN in Dokploy or .env file.")
        sys.exit(1)

    logger.info("Initializing Telegram Metadata Remover Bot...")
    if settings.allowed_user_ids:
        logger.info(f"Bot configured in PRIVATE mode. Allowed Telegram User IDs: {settings.allowed_user_ids}")
    else:
        logger.warning("Bot configured in OPEN mode (ALLOWED_USER_IDS is empty). Anyone can use the bot.")

    session = None
    if settings.telegram_api_server:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer

        logger.info(f"Using custom Telegram Bot API server: {settings.telegram_api_server}")
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.telegram_api_server, is_local=True)
        )

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    # Rejestracja middleware weryfikacji uprawnień (whitelist)
    dp.message.middleware(WhitelistMiddleware(settings=settings))

    # Przekazanie settings jako zależności do handlerów
    dp["settings"] = settings

    # Rejestracja routera z handlerami
    dp.include_router(router)

    # Upewniamy się, że nie ma wiszącego webhooka i ignorujemy stare oczekujące wiadomości
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(f"Bot started successfully! Username: @{bot_info.username} (ID: {bot_info.id})")
    logger.info("Listening for updates via Long Polling...")

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Closing bot session...")
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("telegram_bot").info("Bot stopped.")

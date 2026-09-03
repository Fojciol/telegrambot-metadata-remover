import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable, Dict, Any, Awaitable

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile, TelegramObject
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from src.config import Settings
from src.metadata import inspect_metadata, strip_metadata

logger = logging.getLogger(__name__)
router = Router()


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id

        # Jeśli lista jest zdefiniowana i nie zawiera tego użytkownika, blokujemy
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            logger.warning(f"Unauthorized access attempt by user_id={user_id} (@{event.from_user.username})")
            await event.answer(
                f"⛔ <b>Brak dostępu</b>\n\n"
                f"Ten bot jest prywatny.\n"
                f"Twoje Telegram ID to: <code>{user_id}</code>\n\n"
                f"💡 <i>Przekaż to ID administratorowi, aby dodał Cię do listy uprawnionych (ALLOWED_USER_IDS w Dokploy).</i>"
            )
            return

        return await handler(event, data)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings):
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(
        f"👋 <b>Cześć! Jestem Twoim botem do usuwania metadanych.</b>\n\n"
        f"🛡️ Usuwam ukryte dane ze zdjęć, filmów i dokumentów:\n"
        f"• 📍 Współrzędne GPS (gdzie zrobiono zdjęcie)\n"
        f"• 📱 Model telefonu / aparatu i obiektywu\n"
        f"• 📅 Dokładną datę i godzinę wykonania\n"
        f"• 💻 Wersję oprogramowania, dane edycji\n"
        f"• 👤 Dane autora / profilu\n\n"
        f"🚀 <b>Jak używać?</b>\n"
        f"Po prostu wyślij mi plik lub zdjęcie. Bot oczyści go bezstratnie (100% jakości bez ponownej kompresji) "
        f"i odeśle w bezpiecznej formie wraz z raportem usuniętych danych.\n\n"
        f"💡 <i>Wskazówka: Aby zachować pełne oryginalne metadane przed usunięciem i najwyższą jakość, "
        f"najlepiej wysyłać zdjęcia jako <b>Plik / Dokument (bez kompresji)</b>.</i>\n\n"
        f"🆔 Twoje Telegram ID: <code>{user_id}</code>"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Pomoc - Telegram Metadata Remover</b>\n\n"
        "1. <b>Obsługiwane formaty:</b> Obrazy (JPEG, PNG, HEIC, WEBP, TIFF itp.), wideo (MP4, MOV itp.), dokumenty (PDF) i pliki audio.\n"
        "2. <b>Bezstratność:</b> Bot używa silnika <b>ExifTool</b>, usuwając metadane bezpośrednio ze struktury pliku bez rekompresji obrazu.\n"
        "3. <b>Prywatność:</b> Po przetworzeniu i odesłaniu plik jest <b>natychmiast trwale kasowany</b> z dysku serwera.\n"
        "4. <b>Maksymalny rozmiar:</b> do 20 MB (standardowy limit Telegram Bot API)."
    )


@router.message(Command("id"))
async def cmd_id(message: Message, settings: Settings):
    user_id = message.from_user.id if message.from_user else 0
    is_allowed = not settings.allowed_user_ids or user_id in settings.allowed_user_ids
    status = "✅ Autoryzowany" if is_allowed else "❌ Brak uprawnień"
    await message.answer(
        f"👤 <b>Informacje o koncie:</b>\n"
        f"• Twoje Telegram ID: <code>{user_id}</code>\n"
        f"• Status: {status}"
    )


async def process_media_file(
    message: Message,
    bot: Bot,
    file_id: str,
    original_filename: str,
    file_size: int,
    settings: Settings
):
    """Główna funkcja pobierająca, analizująca, oczyszczająca i odsyłająca plik."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if file_size and file_size > max_bytes:
        await message.reply(
            f"⚠️ <b>Plik jest za duży!</b>\n"
            f"Rozmiar: {file_size / (1024 * 1024):.1f} MB. Maksymalny dozwolony rozmiar to {settings.max_file_size_mb} MB."
        )
        return

    # Informacja o przetwarzaniu
    status_msg = await message.reply("⏳ <i>Pobieram i analizuję metadane...</i>")
    await bot.send_chat_action(chat_id=message.chat.id, action="upload_document")

    # Unikalny katalog roboczy dla tego zadania
    task_dir = settings.temp_dir / f"task_{uuid.uuid4().hex}"
    task_dir.mkdir(parents=True, exist_ok=True)
    local_file_path = task_dir / original_filename

    try:
        # Pobieranie pliku z Telegrama
        file_obj = await bot.get_file(file_id)
        if not file_obj.file_path:
            raise RuntimeError("Nie udało się pobrać ścieżki pliku z Telegram API.")

        await bot.download_file(file_obj.file_path, destination=local_file_path)

        # 1. Odczyt metadanych do raportu
        report = await inspect_metadata(local_file_path)

        # 2. Usunięcie metadanych
        await status_msg.edit_text("🧹 <i>Usuwam ukryte metadane (ExifTool)...</i>")
        success = await strip_metadata(local_file_path)

        if not success or not local_file_path.exists():
            await status_msg.edit_text("❌ <b>Wystąpił błąd podczas oczyszczania metadanych z tego pliku.</b>")
            return

        # 3. Przygotowanie oczyszczonego pliku do odesłania
        clean_filename = f"clean_{original_filename}" if not original_filename.startswith("clean_") else original_filename
        input_file = FSInputFile(path=local_file_path, filename=clean_filename)

        report_caption = report.format_telegram_message()

        # Odsyłamy jako dokument, aby Telegram nie kompresował pliku i nie dodawał własnych artefaktów
        await message.reply_document(
            document=input_file,
            caption=report_caption
        )

        # Usunięcie komunikatu o statusie
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error processing file for message {message.message_id}: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Wystąpił błąd podczas przetwarzania pliku:</b>\n<code>{type(e).__name__}: {str(e)[:150]}</code>"
        )
    finally:
        # Zawsze bezpiecznie usuwamy katalog tymczasowy po zakończeniu operacji
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, settings: Settings):
    # message.photo zawiera listę rozmiarów; ostatni [-1] to najwyższa dostępna rozdzielczość
    photo = message.photo[-1]
    filename = f"photo_{photo.file_unique_id}.jpg"
    await process_media_file(
        message=message,
        bot=bot,
        file_id=photo.file_id,
        original_filename=filename,
        file_size=photo.file_size or 0,
        settings=settings
    )


@router.message(F.document)
async def handle_document(message: Message, bot: Bot, settings: Settings):
    doc = message.document
    filename = doc.file_name or f"document_{doc.file_unique_id}"
    await process_media_file(
        message=message,
        bot=bot,
        file_id=doc.file_id,
        original_filename=filename,
        file_size=doc.file_size or 0,
        settings=settings
    )


@router.message(F.video)
async def handle_video(message: Message, bot: Bot, settings: Settings):
    video = message.video
    filename = video.file_name or f"video_{video.file_unique_id}.mp4"
    await process_media_file(
        message=message,
        bot=bot,
        file_id=video.file_id,
        original_filename=filename,
        file_size=video.file_size or 0,
        settings=settings
    )


@router.message(F.audio)
async def handle_audio(message: Message, bot: Bot, settings: Settings):
    audio = message.audio
    filename = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
    await process_media_file(
        message=message,
        bot=bot,
        file_id=audio.file_id,
        original_filename=filename,
        file_size=audio.file_size or 0,
        settings=settings
    )

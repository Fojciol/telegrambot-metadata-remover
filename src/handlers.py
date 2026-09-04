import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable, Dict, Any, Awaitable

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    TelegramObject,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest

from src.config import Settings
from src.metadata import inspect_metadata, strip_metadata
from src.video_uniquifier import uniquify_video

logger = logging.getLogger(__name__)
router = Router()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v", ".3gp"}


def is_video_file(filename: str, mime_type: str = "") -> bool:
    """Sprawdza, czy dany plik jest plikiem wideo na podstawie rozszerzenia lub typu MIME."""
    ext = Path(filename).suffix.lower()
    return ext in VIDEO_EXTENSIONS or (bool(mime_type) and "video" in mime_type.lower())


def get_uniquify_keyboard(is_retry: bool = False) -> InlineKeyboardMarkup:
    """Zwraca przyciski wyboru trybu unikalizacji wideo."""
    prefix = "🔄 Kolejna kopia" if is_retry else "⚡ Zunikalizuj"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{prefix} (Łagodna)",
                    callback_data="unq:mild"
                ),
                InlineKeyboardButton(
                    text=f"{prefix} (Lustro)",
                    callback_data="unq:deep"
                )
            ]
        ]
    )


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
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        user_id = user.id

        # Jeśli lista jest zdefiniowana i nie zawiera tego użytkownika, blokujemy
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            logger.warning(f"Unauthorized access attempt by user_id={user_id} (@{user.username})")
            if isinstance(event, Message):
                await event.answer(
                    f"⛔ <b>Brak dostępu</b>\n\n"
                    f"Ten bot jest prywatny.\n"
                    f"Twoje Telegram ID to: <code>{user_id}</code>\n\n"
                    f"💡 <i>Przekaż to ID administratorowi, aby dodał Cię do listy uprawnionych (ALLOWED_USER_IDS w Dokploy).</i>"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(f"⛔ Brak dostępu. Twoje ID to: {user_id}", show_alert=True)
            return

        return await handler(event, data)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings):
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(
        f"👋 <b>Cześć! Jestem Twoim botem do usuwania metadanych i unikalizacji wideo.</b>\n\n"
        f"🛡️ <b>Usuwanie metadanych (ExifTool):</b>\n"
        f"• 📍 Współrzędne GPS (gdzie zrobiono zdjęcie/film)\n"
        f"• 📱 Model telefonu / aparatu i obiektywu\n"
        f"• 📅 Dokładną datę i godzinę wykonania\n"
        f"• 💻 Wersję oprogramowania, dane edycji i profilu\n\n"
        f"⚡ <b>Unikalizator wideo (Bypass Meta ThreatExchange / TikTok):</b>\n"
        f"• Po przesłaniu wideo możesz jednym kliknięciem wygenerować zunikalizowane wersje z losowymi parametrami (mikro-zoom, zmiana prędkości, ziarno, audio, opcjonalne lustro).\n"
        f"• Omija algorytmy vPDQ, TMK oraz audio fingerprinting – idealne do publikacji tego samego filmu na wielu kontach bez obcinania zasięgów!\n\n"
        f"🚀 <b>Jak używać?</b>\n"
        f"Po prostu wyślij mi plik lub wideo (najlepiej jako <b>Plik / Dokument bez kompresji</b>).\n\n"
        f"🆔 Twoje Telegram ID: <code>{user_id}</code>"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings):
    await message.answer(
        "📖 <b>Pomoc - Telegram Metadata Remover & Video Uniquifier</b>\n\n"
        "1. <b>Obsługiwane formaty:</b> Obrazy (JPEG, PNG, HEIC, WEBP, TIFF), wideo (MP4, MOV itp.), dokumenty (PDF) i audio.\n"
        "2. <b>Bezstratność:</b> Bot używa silnika <b>ExifTool</b> do bezpośredniego usuwania metadanych ze struktury pliku.\n"
        "3. <b>Unikalizacja wideo (FFmpeg):</b> Pod każdym przesłanym filmem znajdziesz przyciski do wygenerowania unikalnej kopii z nowym podpisem percepcyjnym.\n"
        "   • <b>Tryb Łagodny:</b> mikro-zoom, zmiana tempa, subtelny szum matrycy, korekta audio (bezpieczny dla napisów i twarzy).\n"
        "   • <b>Tryb Głęboki (Lustro):</b> wszystko powyższe + poziome odbicie lustrzane.\n"
        "4. <b>Prywatność:</b> Po przetworzeniu i odesłaniu plik jest <b>natychmiast trwale kasowany</b> z dysku serwera.\n"
        f"5. <b>Maksymalny rozmiar:</b> do {settings.max_file_size_mb} MB."
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

        # Sprawdzenie czy plik jest wideo (aby dodać przyciski unikalizacji)
        is_video = (
            is_video_file(original_filename)
            or (message.video is not None)
            or (message.document and is_video_file(message.document.file_name or "", message.document.mime_type or ""))
        )
        reply_markup = get_uniquify_keyboard(is_retry=False) if is_video else None

        # Odsyłamy jako dokument, aby Telegram nie kompresował pliku i nie dodawał własnych artefaktów
        await message.reply_document(
            document=input_file,
            caption=report_caption,
            reply_markup=reply_markup
        )

        # Usunięcie komunikatu o statusie
        try:
            await status_msg.delete()
        except Exception:
            pass

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest processing file: {e}")
        err_text = str(e).lower()
        if "file is too big" in err_text:
            await status_msg.edit_text(
                f"⚠️ <b>Plik przekracza limit oficjalnego serwera Telegram Bot API!</b>\n\n"
                f"Wykryty rozmiar: <b>{file_size / (1024 * 1024):.1f} MB</b>.\n"
                f"Domyślne serwery Telegrama (api.telegram.org) blokują pobieranie plików powyżej <b>20 MB</b> przez boty.\n\n"
                f"💡 <i>Aby bot mógł pobierać pliki do {settings.max_file_size_mb} MB (lub nawet 2 GB), "
                f"wystarczy uruchomić w Dokploy lokalny kontener <b>telegram-bot-api</b> i ustawić zmienną <code>TELEGRAM_API_SERVER</code>.</i>"
            )
        else:
            await status_msg.edit_text(
                f"❌ <b>Błąd Telegram API:</b>\n<code>{str(e)[:150]}</code>"
            )
    except Exception as e:
        logger.error(f"Error processing file for message {message.message_id}: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Wystąpił błąd podczas przetwarzania pliku:</b>\n<code>{type(e).__name__}: {str(e)[:150]}</code>"
        )
    finally:
        # Zawsze bezpiecznie usuwamy katalog tymczasowy po zakończeniu operacji
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


@router.callback_query(F.data.startswith("unq:"))
async def handle_uniquify_callback(query: CallbackQuery, bot: Bot, settings: Settings):
    """Obsługuje kliknięcie przycisków unikalizacji wideo."""
    mode = query.data.split(":")[1] if ":" in query.data else "mild"
    msg = query.message
    if not msg:
        await query.answer("Wiadomość wygasła.", show_alert=True)
        return

    file_id = None
    filename = "video.mp4"
    file_size = 0

    if msg.document:
        file_id = msg.document.file_id
        filename = msg.document.file_name or "video.mp4"
        file_size = msg.document.file_size or 0
    elif msg.video:
        file_id = msg.video.file_id
        filename = msg.video.file_name or "video.mp4"
        file_size = msg.video.file_size or 0

    if not file_id:
        await query.answer("Nie znaleziono pliku wideo do unikalizacji.", show_alert=True)
        return

    mode_title = "Głęboka (Lustro)" if mode == "deep" else "Łagodna"
    await query.answer(f"Rozpoczynam unikalizację: {mode_title}")

    status_msg = await msg.reply(
        f"⏳ <i>Renderuję unikalną kopię wideo w trybie <b>{mode_title}</b> (FFmpeg + ExifTool)...</i>"
    )
    await bot.send_chat_action(chat_id=msg.chat.id, action="upload_document")

    task_dir = settings.temp_dir / f"unq_{uuid.uuid4().hex}"
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / filename

    stem = Path(filename).stem
    out_filename = f"unique_{stem}.mp4" if not stem.startswith("unique_") else f"unique_{uuid.uuid4().hex[:4]}_{stem}.mp4"
    output_path = task_dir / out_filename

    try:
        file_obj = await bot.get_file(file_id)
        if not file_obj.file_path:
            raise RuntimeError("Nie udało się pobrać pliku z serwera Telegram.")

        await bot.download_file(file_obj.file_path, destination=input_path)

        success, params = await uniquify_video(input_path, output_path, mode=mode)
        if not success or not output_path.exists() or not params:
            await status_msg.edit_text("❌ <b>Błąd podczas renderowania unikalnego wideo w FFmpeg.</b>")
            return

        caption = params.format_telegram_caption()
        out_file = FSInputFile(path=output_path, filename=out_filename)

        # Odsyłamy unikalne wideo z przyciskami umożliwiającymi wygenerowanie kolejnej kopii
        await msg.reply_document(
            document=out_file,
            caption=caption,
            reply_markup=get_uniquify_keyboard(is_retry=True)
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest in uniquify callback: {e}")
        err_text = str(e).lower()
        if "file is too big" in err_text:
            await status_msg.edit_text(
                "⚠️ <b>Plik przekracza limit pobierania Telegram API (20 MB)!</b>\n\n"
                "Skorzystaj z lokalnego serwera Telegram Bot API, aby przetwarzać większe pliki."
            )
        else:
            await status_msg.edit_text(f"❌ <b>Błąd Telegram API:</b> <code>{str(e)[:150]}</code>")
    except Exception as e:
        logger.error(f"Error during video uniquify callback: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Wystąpił błąd podczas unikalizacji:</b>\n<code>{type(e).__name__}: {str(e)[:150]}</code>"
        )
    finally:
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, settings: Settings):
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

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable, Dict, Any, Awaitable, Optional, Tuple

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
from src.video_uniquifier import (
    uniquify_video,
    uniquify_photo,
    create_zip_archive
)

logger = logging.getLogger(__name__)
router = Router()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v", ".3gp"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp"}


def is_video_file(filename: str, mime_type: str = "") -> bool:
    """Sprawdza, czy dany plik jest plikiem wideo na podstawie rozszerzenia lub typu MIME."""
    ext = Path(filename).suffix.lower()
    return ext in VIDEO_EXTENSIONS or (bool(mime_type) and "video" in mime_type.lower())


def is_photo_file(filename: str, mime_type: str = "") -> bool:
    """Sprawdza, czy dany plik jest obrazem na podstawie rozszerzenia lub typu MIME."""
    ext = Path(filename).suffix.lower()
    return ext in PHOTO_EXTENSIONS or (bool(mime_type) and "image" in mime_type.lower())


def get_video_keyboard(is_retry: bool = False) -> InlineKeyboardMarkup:
    """Zwraca przyciski wyboru dla pliku wideo (unikalizacja + ZIP)."""
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
            ],
            [
                InlineKeyboardButton(
                    text="📦 Pobierz jako ZIP",
                    callback_data="zip"
                )
            ]
        ]
    )


def get_photo_keyboard(is_retry: bool = False) -> InlineKeyboardMarkup:
    """Zwraca przyciski wyboru dla zdjęcia (Anti-AI unikalizacja + ZIP)."""
    prefix = "🔄 Kolejna (Anti-AI)" if is_retry else "⚡ Zunikalizuj (Anti-AI / SynthID)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=prefix,
                    callback_data="unq_photo"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Pobierz jako ZIP",
                    callback_data="zip"
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
        f"👋 <b>Cześć! Jestem zaawansowanym botem do usuwania metadanych i unikalizacji mediów.</b>\n\n"
        f"🛡️ <b>Usuwanie metadanych i śladów AI (ExifTool):</b>\n"
        f"• 🤖 Usuwa manifesty <b>C2PA / JUMBF (Content Credentials)</b> stosowane przez generatory AI (Kling AI, Nanabanapro, Midjourney, DALL-E, Sora)\n"
        f"• 📍 Usuwa współrzędne GPS, model telefonu/aparatu, dokładne daty i historię edycji\n"
        f"• 💬 Usuwa ukryte prompty, workflow i parametry generowania\n\n"
        f"⚡ <b>Unikalizator wideo i zdjęć (Bypass Meta ThreatExchange / TikTok / SynthID):</b>\n"
        f"• Omija algorytmy vPDQ, TMK oraz niewidzialne znaki wodne <b>SynthID</b> (Kling AI / Google)\n"
        f"• Aplikuje mikromodyfikacje (zoom, przesunięcie siatki, tempo, subtelne ziarno i audio)\n"
        f"• Pozwala generować wiele unikalnych kopii dla różnych kont jednym kliknięciem!\n\n"
        f"📱 <b>Czyste pliki dla iPhone:</b>\n"
        f"• Wszystkie pliki są wysyłane jako surowe dokumenty (bez playera wideo i bez psucia formatu)\n"
        f"• Przycisk <b>📦 Pobierz jako ZIP</b> pozwala na 100% sterylną izolację na iOS bez powiązań z aplikacją Zdjęcia\n\n"
        f"🆔 Twoje Telegram ID: <code>{user_id}</code>"
    )


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings):
    await message.answer(
        "📖 <b>Pomoc - Telegram Metadata Remover & AI Uniquifier</b>\n\n"
        "1. <b>Obsługiwane pliki:</b> Wideo (MP4, MOV itp.), zdjęcia (JPEG, PNG, HEIC, WEBP itp.), dokumenty (PDF) i audio.\n"
        "2. <b>Generatory AI:</b> Bot bezpowrotnie niszczy manifesty C2PA/JUMBF oraz tagi generatorów (Kling AI, Nanabanapro, Midjourney, ComfyUI itp.).\n"
        "3. <b>Niewidzialne znaki wodne (SynthID):</b> Aby zniszczyć znak wodny w pikselach, użyj przycisków <b>⚡ Zunikalizuj</b> pod przesłanym plikiem.\n"
        "4. <b>Zapisywanie na iPhone:</b>\n"
        "   • Bot wysyła plik z blokadą autodetekcji mediów, więc Telegram traktuje go jak czysty plik.\n"
        "   • Kliknięcie <b>📦 Pobierz jako ZIP</b> pakuje plik do archiwum .zip. Zapisz go w aplikacji 'Pliki' na iPhone, aby mieć 100% sterylny materiał.\n"
        f"5. <b>Maksymalny rozmiar pliku:</b> do {settings.max_file_size_mb} MB."
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
    status_msg = await message.reply("⏳ <i>Pobieram i analizuję metadane oraz ślady AI...</i>")
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

        # 1. Odczyt metadanych do raportu (w tym śladów AI)
        report = await inspect_metadata(local_file_path)

        # 2. Usunięcie metadanych (EXIF, GPS, C2PA / JUMBF)
        await status_msg.edit_text("🧹 <i>Usuwam metadane i manifesty C2PA (ExifTool)...</i>")
        success = await strip_metadata(local_file_path)

        if not success or not local_file_path.exists():
            await status_msg.edit_text("❌ <b>Wystąpił błąd podczas oczyszczania metadanych z tego pliku.</b>")
            return

        # 3. Przygotowanie oczyszczonego pliku do odesłania
        clean_filename = f"clean_{original_filename}" if not original_filename.startswith("clean_") else original_filename
        input_file = FSInputFile(path=local_file_path, filename=clean_filename)

        report_caption = report.format_telegram_message()

        # Dobór odpowiedniej klawiatury w zależności od typu pliku
        is_video = (
            is_video_file(original_filename)
            or (message.video is not None)
            or (message.document and is_video_file(message.document.file_name or "", message.document.mime_type or ""))
        )
        is_photo = (
            is_photo_file(original_filename)
            or (message.photo is not None)
            or (message.document and is_photo_file(message.document.file_name or "", message.document.mime_type or ""))
        )

        reply_markup = None
        if is_video:
            reply_markup = get_video_keyboard(is_retry=False)
        elif is_photo:
            reply_markup = get_photo_keyboard(is_retry=False)

        # Odsyłamy jako surowy dokument z disable_content_type_detection=True
        # aby Telegram nie tworzył wbudowanego playera wideo na iPhone
        await message.reply_document(
            document=input_file,
            caption=report_caption,
            reply_markup=reply_markup,
            disable_content_type_detection=True
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


def extract_media_from_message(msg: Message) -> Tuple[Optional[str], str, int]:
    """Wyciąga file_id, nazwę pliku oraz rozmiar z wiadomości."""
    if msg.document:
        return msg.document.file_id, msg.document.file_name or "file.bin", msg.document.file_size or 0
    if msg.video:
        return msg.video.file_id, msg.video.file_name or "video.mp4", msg.video.file_size or 0
    if msg.photo:
        photo = msg.photo[-1]
        return photo.file_id, f"photo_{photo.file_unique_id}.jpg", photo.file_size or 0
    return None, "file.bin", 0


@router.callback_query(F.data.startswith("unq:"))
async def handle_uniquify_video_callback(query: CallbackQuery, bot: Bot, settings: Settings):
    """Obsługuje kliknięcie przycisków unikalizacji wideo."""
    mode = query.data.split(":")[1] if ":" in query.data else "mild"
    msg = query.message
    if not msg:
        await query.answer("Wiadomość wygasła.", show_alert=True)
        return

    file_id, filename, file_size = extract_media_from_message(msg)
    if not file_id:
        await query.answer("Nie znaleziono pliku wideo do unikalizacji.", show_alert=True)
        return

    mode_title = "Głęboka (Lustro)" if mode == "deep" else "Łagodna"
    await query.answer(f"Rozpoczynam unikalizację: {mode_title}")

    status_msg = await msg.reply(
        f"⏳ <i>Renderuję unikalną kopię wideo w trybie <b>{mode_title}</b> (FFmpeg + ExifTool)...</i>"
    )
    await bot.send_chat_action(chat_id=msg.chat.id, action="upload_document")

    task_dir = settings.temp_dir / f"unq_vid_{uuid.uuid4().hex}"
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

        # Odsyłamy unikalne wideo jako dokument bez autodetekcji mediów
        await msg.reply_document(
            document=out_file,
            caption=caption,
            reply_markup=get_video_keyboard(is_retry=True),
            disable_content_type_detection=True
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest in video uniquify: {e}")
        await status_msg.edit_text(f"❌ <b>Błąd Telegram API:</b> <code>{str(e)[:150]}</code>")
    except Exception as e:
        logger.error(f"Error during video uniquify callback: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Wystąpił błąd podczas unikalizacji wideo:</b>\n<code>{type(e).__name__}: {str(e)[:150]}</code>"
        )
    finally:
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


@router.callback_query(F.data == "unq_photo")
async def handle_uniquify_photo_callback(query: CallbackQuery, bot: Bot, settings: Settings):
    """Obsługuje kliknięcie przycisku unikalizacji zdjęcia (rozbijanie SynthID / Anti-AI)."""
    msg = query.message
    if not msg:
        await query.answer("Wiadomość wygasła.", show_alert=True)
        return

    file_id, filename, file_size = extract_media_from_message(msg)
    if not file_id:
        await query.answer("Nie znaleziono zdjęcia do unikalizacji.", show_alert=True)
        return

    await query.answer("Rozpoczynam unikalizację zdjęcia...")
    status_msg = await msg.reply("⏳ <i>Unikalizuję zdjęcie i rozbijam ślady SynthID (FFmpeg + ExifTool)...</i>")
    await bot.send_chat_action(chat_id=msg.chat.id, action="upload_document")

    task_dir = settings.temp_dir / f"unq_photo_{uuid.uuid4().hex}"
    task_dir.mkdir(parents=True, exist_ok=True)
    input_path = task_dir / filename

    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".jpg"
    out_filename = f"unique_{stem}{suffix}" if not stem.startswith("unique_") else f"unique_{uuid.uuid4().hex[:4]}_{stem}{suffix}"
    output_path = task_dir / out_filename

    try:
        file_obj = await bot.get_file(file_id)
        if not file_obj.file_path:
            raise RuntimeError("Nie udało się pobrać pliku ze serwera Telegram.")

        await bot.download_file(file_obj.file_path, destination=input_path)

        success, params = await uniquify_photo(input_path, output_path)
        if not success or not output_path.exists() or not params:
            await status_msg.edit_text("❌ <b>Błąd podczas unikalizacji zdjęcia.</b>")
            return

        caption = params.format_telegram_caption()
        out_file = FSInputFile(path=output_path, filename=out_filename)

        await msg.reply_document(
            document=out_file,
            caption=caption,
            reply_markup=get_photo_keyboard(is_retry=True),
            disable_content_type_detection=True
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error during photo uniquify callback: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Wystąpił błąd:</b> <code>{type(e).__name__}: {str(e)[:150]}</code>")
    finally:
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


@router.callback_query(F.data == "zip")
async def handle_zip_callback(query: CallbackQuery, bot: Bot, settings: Settings):
    """Pakuje plik z wiadomości do archiwum .zip i odsyła go użytkownikowi."""
    msg = query.message
    if not msg:
        await query.answer("Wiadomość wygasła.", show_alert=True)
        return

    file_id, filename, file_size = extract_media_from_message(msg)
    if not file_id:
        await query.answer("Nie znaleziono pliku do spakowania.", show_alert=True)
        return

    await query.answer("Tworzę paczkę ZIP...")
    status_msg = await msg.reply("📦 <i>Pakuję plik do sterylnego archiwum ZIP...</i>")
    await bot.send_chat_action(chat_id=msg.chat.id, action="upload_document")

    task_dir = settings.temp_dir / f"zip_{uuid.uuid4().hex}"
    task_dir.mkdir(parents=True, exist_ok=True)
    local_path = task_dir / filename

    zip_filename = f"{Path(filename).stem}.zip"
    zip_path = task_dir / zip_filename

    try:
        file_obj = await bot.get_file(file_id)
        if not file_obj.file_path:
            raise RuntimeError("Nie udało się pobrać pliku.")

        await bot.download_file(file_obj.file_path, destination=local_path)

        success = create_zip_archive(local_path, zip_path)
        if not success or not zip_path.exists():
            await status_msg.edit_text("❌ <b>Nie udało się utworzyć archiwum ZIP.</b>")
            return

        zip_input_file = FSInputFile(path=zip_path, filename=zip_filename)
        zip_caption = (
            "📦 <b>Plik pomyślnie spakowany do archiwum ZIP!</b>\n\n"
            "💡 <b>Instrukcja dla użytkowników iPhone:</b>\n"
            "1. Kliknij na plik ZIP i wybierz <b>Zapisz w Plikach</b> (np. 'Na moim iPhonie').\n"
            "2. W aplikacji 'Pliki' kliknij archiwum raz, aby je rozpakować.\n"
            "🛡️ <i>W ten sposób plik ma 100% sterylną izolację i nie otrzymuje żadnego systemowego znacznika Telegrama.</i>"
        )

        await msg.reply_document(
            document=zip_input_file,
            caption=zip_caption,
            disable_content_type_detection=True
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error during zip creation: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Błąd podczas tworzenia ZIP:</b> <code>{str(e)[:150]}</code>")
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

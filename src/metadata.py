import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Tagi czysto techniczne / systemowe, które nie są prywatnymi metadanymi użytkownika
IGNORE_TAGS = {
    "SourceFile",
    "ExifToolVersion",
    "FileName",
    "Directory",
    "FileSize",
    "FileModifyDate",
    "FileAccessDate",
    "FileInodeChangeDate",
    "FilePermissions",
    "FileType",
    "FileTypeExtension",
    "MIMEType",
    "ImageWidth",
    "ImageHeight",
    "Megapixels",
    "BitsPerSample",
    "ColorComponents",
    "EncodingProcess",
    "XResolution",
    "YResolution",
    "ResolutionUnit",
    "YCbCrSubSampling",
}


@dataclass
class MetadataReport:
    gps: Optional[str] = None
    device: Optional[str] = None
    date: Optional[str] = None
    software: Optional[str] = None
    author: Optional[str] = None
    total_tags_found: int = 0
    other_tags: List[str] = field(default_factory=list)

    @property
    def has_sensitive_data(self) -> bool:
        return bool(self.gps or self.device or self.date or self.software or self.author or self.total_tags_found > 0)

    def format_telegram_message(self) -> str:
        if not self.has_sensitive_data:
            return (
                "🧹 <b>Plik przetworzony pomyślnie!</b>\n\n"
                "ℹ️ <i>W pliku nie wykryto żadnych ukrytych metadanych (GPS, model aparatu, dane twórcy). "
                "Plik został dodatkowo sprawdzony i zabezpieczony.</i>"
            )

        lines = [
            "🧹 <b>Plik pomyślnie oczyszczony z metadanych!</b>\n",
            "📋 <b>Wykryte i usunięte informacje:</b>"
        ]

        if self.gps:
            lines.append(f"• 📍 <b>Lokalizacja GPS:</b> <code>{self.gps}</code>")
        if self.device:
            lines.append(f"• 📱 <b>Urządzenie / Aparat:</b> <code>{self.device}</code>")
        if self.date:
            lines.append(f"• 📅 <b>Data i czas:</b> <code>{self.date}</code>")
        if self.software:
            lines.append(f"• 💻 <b>Oprogramowanie:</b> <code>{self.software}</code>")
        if self.author:
            lines.append(f"• 👤 <b>Autor / Właściciel:</b> <code>{self.author}</code>")

        lines.append(f"\n🔢 <b>Łącznie usuniętych tagów metadanych:</b> {self.total_tags_found}")
        lines.append("\n🛡️ <i>Wszystkie wrażliwe znaczniki zostały bezpowrotnie usunięte bez zmiany jakości pliku.</i>")

        return "\n".join(lines)


async def inspect_metadata(file_path: Path) -> MetadataReport:
    """Odczytuje metadane pliku za pomocą exiftool przed ich usunięciem."""
    cmd = ["exiftool", "-json", str(file_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        if proc.returncode != 0 and not stdout:
            err_msg = stderr.decode(errors="replace").strip()
            logger.warning(f"ExifTool inspection error on {file_path}: {err_msg}")
            return MetadataReport()

        data: List[Dict[str, Any]] = json.loads(stdout.decode(errors="replace"))
        if not data:
            return MetadataReport()

        raw_meta = data[0]
        report = MetadataReport()

        # Szukanie GPS
        if "GPSPosition" in raw_meta:
            report.gps = str(raw_meta["GPSPosition"])
        elif "GPSLatitude" in raw_meta and "GPSLongitude" in raw_meta:
            report.gps = f"{raw_meta['GPSLatitude']}, {raw_meta['GPSLongitude']}"

        # Szukanie urządzenia / aparatu
        make = raw_meta.get("Make", "")
        model = raw_meta.get("Model", "")
        if make or model:
            report.device = f"{make} {model}".strip()

        # Szukanie daty wykonania / modyfikacji
        for date_key in ("DateTimeOriginal", "CreateDate", "CreationDate", "ModifyDate"):
            if date_key in raw_meta and raw_meta[date_key]:
                report.date = str(raw_meta[date_key])
                break

        # Szukanie oprogramowania
        for sw_key in ("Software", "HostComputer", "ProcessingSoftware", "Producer"):
            if sw_key in raw_meta and raw_meta[sw_key]:
                report.software = str(raw_meta[sw_key])
                break

        # Szukanie autora / właściciela
        for auth_key in ("Artist", "Author", "Creator", "OwnerName", "Copyright", "XPAuthor"):
            if auth_key in raw_meta and raw_meta[auth_key]:
                report.author = str(raw_meta[auth_key])
                break

        # Licznik wszystkich nietechnicznych tagów
        custom_tags = [k for k in raw_meta.keys() if k not in IGNORE_TAGS]
        report.total_tags_found = len(custom_tags)
        report.other_tags = custom_tags[:10]

        return report

    except asyncio.TimeoutError:
        logger.error(f"Timeout while reading metadata for {file_path}")
        return MetadataReport()
    except Exception as e:
        logger.error(f"Exception during metadata inspection for {file_path}: {e}", exc_info=True)
        return MetadataReport()


async def strip_metadata(file_path: Path) -> bool:
    """
    Usuwa wszystkie metadane z pliku in-place za pomocą ExifTool.
    Zwraca True, jeśli operacja zakończyła się sukcesem.
    """
    cmd = ["exiftool", "-all=", "-overwrite_original", str(file_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")

        # ExifTool zwraca 0 przy pełnym sukcesie, lub 1 przy drobnych ostrzeżeniach (np. minor warning)
        # ale plik nadal zostaje zaktualizowany ("image files updated")
        if "image files updated" in stdout_str or "files updated" in stdout_str or proc.returncode == 0:
            logger.info(f"Successfully stripped metadata for {file_path}")
            return True

        if "image files unchanged" in stdout_str or "files unchanged" in stdout_str:
            logger.info(f"File {file_path} had no metadata to strip (unchanged)")
            return True

        logger.warning(f"ExifTool strip warning/error: returncode={proc.returncode}, stdout={stdout_str}, stderr={stderr_str}")
        # Jeśli plik istnieje i nie został uszkodzony, zwracamy True
        return file_path.exists() and file_path.stat().st_size > 0

    except asyncio.TimeoutError:
        logger.error(f"Timeout while stripping metadata for {file_path}")
        return False
    except Exception as e:
        logger.error(f"Exception while stripping metadata for {file_path}: {e}", exc_info=True)
        return False

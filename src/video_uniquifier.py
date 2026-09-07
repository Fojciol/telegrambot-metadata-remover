import asyncio
import logging
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.metadata import strip_metadata

logger = logging.getLogger(__name__)


@dataclass
class UniquifyParams:
    mode: str
    crop_factor: float
    speed: float
    gamma: float
    contrast: float
    brightness: float
    noise_strength: int
    flip: bool

    def format_telegram_caption(self) -> str:
        zoom_pct = round((1.0 - self.crop_factor) * 100.0, 1)
        speed_diff = round((self.speed - 1.0) * 100.0, 1)
        speed_str = f"{'+' if speed_diff > 0 else ''}{speed_diff}% ({self.speed:.3f}x)"
        mode_title = "🔥 Głęboka (Lustro)" if self.flip else "✨ Łagodna"

        lines = [
            f"⚡ <b>Wideo zunikalizowane!</b> [{mode_title}]\n",
            "🛡️ <b>Modyfikacje percepcyjne (Bypass vPDQ/TMK/SynthID/Audio):</b>",
            f"• 🔍 <b>Mikro-zoom kadru:</b> <code>+{zoom_pct}%</code>",
            f"• ⏱️ <b>Korekta tempa wideo/audio:</b> <code>{speed_str}</code>",
            f"• 🎞️ <b>Ziarno matrycy (Noise):</b> <code>Poziom {self.noise_strength}</code>",
            f"• 🎨 <b>Korekta barw:</b> <code>γ={self.gamma:.3f}, c={self.contrast:.3f}</code>",
        ]

        if self.flip:
            lines.append("• 🪞 <b>Odbicie lustrzane:</b> <code>Włączone (hflip)</code>")
        else:
            lines.append("• 🪞 <b>Odbicie lustrzane:</b> <code>Wyłączone (ochrona napisów)</code>")

        lines.append(
            "\n🚀 <i>Wygenerowano unikalny podpis percepcyjny. "
            "Plik jest traktowany przez algorytmy Meta/TikTok jako zupełnie nowe wideo.</i>"
        )
        return "\n".join(lines)


@dataclass
class PhotoUniquifyParams:
    crop_factor: float
    noise_strength: int
    gamma: float
    contrast: float

    def format_telegram_caption(self) -> str:
        zoom_pct = round((1.0 - self.crop_factor) * 100.0, 1)
        return (
            "⚡ <b>Zdjęcie zunikalizowane (Anti-AI / SynthID)!</b>\n\n"
            "🛡️ <b>Zastosowane mikromodyfikacje pikselowe:</b>\n"
            f"• 🔍 <b>Mikro-zoom / przesunięcie siatki:</b> <code>+{zoom_pct}%</code>\n"
            f"• 🎞️ <b>Ziarno matrycy (Anti-SynthID):</b> <code>Poziom {self.noise_strength}</code>\n"
            f"• 🎨 <b>Korekta krzywych gamma:</b> <code>γ={self.gamma:.3f}, c={self.contrast:.3f}</code>\n"
            "• 🧹 <b>Manifesty C2PA / JUMBF:</b> <code>100% zniszczone</code>\n\n"
            "🚀 <i>Rozbito niewidzialne znaki wodne i wygenerowano nowy cyfrowy podpis obrazu.</i>"
        )


def generate_random_params(mode: str = "mild") -> UniquifyParams:
    """Generuje losowy zestaw parametrów dla danego trybu unikalizacji wideo."""
    # Losowy zoom: od 1.2% do 2.5%
    crop_factor = round(random.uniform(0.975, 0.988), 4)

    # Losowa zmiana prędkości: przyspieszenie o 1.2-2.5% lub zwolnienie o 1-2%
    if random.random() > 0.5:
        speed = round(random.uniform(1.012, 1.026), 4)
    else:
        speed = round(random.uniform(0.980, 0.990), 4)

    # Drobne korekty luminancji
    gamma = round(random.uniform(0.985, 1.015), 3)
    contrast = round(random.uniform(0.985, 1.015), 3)
    brightness = round(random.uniform(-0.015, 0.015), 3)

    # Drobny szum rozbijający steganografię i PDQ
    noise_strength = random.choice([2, 3])

    flip = (mode == "deep")

    return UniquifyParams(
        mode=mode,
        crop_factor=crop_factor,
        speed=speed,
        gamma=gamma,
        contrast=contrast,
        brightness=brightness,
        noise_strength=noise_strength,
        flip=flip
    )


def build_filter_chains(params: UniquifyParams) -> Tuple[str, str]:
    """Buduje filtry wideo (-vf) oraz audio (-af) dla FFmpeg."""
    vf_parts = [
        f"crop=w=trunc(iw*{params.crop_factor}/2)*2:h=trunc(ih*{params.crop_factor}/2)*2",
        "scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2",
        f"eq=gamma={params.gamma}:contrast={params.contrast}:brightness={params.brightness}",
        f"noise=alls={params.noise_strength}:allf=t",
        f"setpts=PTS/{params.speed}"
    ]

    if params.flip:
        vf_parts.append("hflip")

    video_filter = ",".join(vf_parts)
    audio_filter = f"atempo={params.speed}"

    return video_filter, audio_filter


async def has_audio_stream(file_path: Path) -> bool:
    """Sprawdza za pomocą ffprobe, czy plik zawiera ścieżkę dźwiękową."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return bool(stdout.strip())
    except Exception as e:
        logger.warning(f"Failed to probe audio stream for {file_path}: {e}")
        return False


def create_zip_archive(source_file: Path, zip_output_path: Path) -> bool:
    """Pakuje pojedynczy plik do archiwum .zip bez katalogów nadrzędnych."""
    try:
        with zipfile.ZipFile(zip_output_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(source_file, arcname=source_file.name)
        return zip_output_path.exists() and zip_output_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"Error creating zip archive: {e}", exc_info=True)
        return False


async def uniquify_photo(
    input_path: Path,
    output_path: Path
) -> Tuple[bool, Optional[PhotoUniquifyParams]]:
    """
    Unikalizuje zdjęcie, aplikując mikro-crop, subtelny szum matrycy rozbijający
    steganografię SynthID oraz drobne przesunięcie gamma, a na końcu
    usuwa wszelkie metadane C2PA i EXIF.
    """
    crop_factor = round(random.uniform(0.985, 0.993), 4)
    gamma = round(random.uniform(0.992, 1.008), 3)
    contrast = round(random.uniform(0.992, 1.008), 3)
    noise_strength = random.choice([2, 3])

    vf = (
        f"crop=w=trunc(iw*{crop_factor}/2)*2:h=trunc(ih*{crop_factor}/2)*2,"
        f"scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2,"
        f"eq=gamma={gamma}:contrast={contrast},"
        f"noise=alls={noise_strength}:allf=t"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-q:v", "2",
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        str(output_path)
    ]

    logger.info(f"Uniquifying photo {input_path} -> {output_path}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            err_text = stderr.decode(errors="replace")[-200:]
            logger.error(f"FFmpeg photo uniquification failed: {err_text}")
            return False, None

        # Usunięcie wszelkich pozostałych metadanych i manifestów C2PA
        await strip_metadata(output_path)

        params = PhotoUniquifyParams(
            crop_factor=crop_factor,
            noise_strength=noise_strength,
            gamma=gamma,
            contrast=contrast
        )
        return True, params

    except Exception as e:
        logger.error(f"Exception during photo uniquification: {e}", exc_info=True)
        return False, None


async def uniquify_video(
    input_path: Path,
    output_path: Path,
    mode: str = "mild"
) -> Tuple[bool, Optional[UniquifyParams]]:
    """
    Przetwarza wideo za pomocą FFmpeg, aplikując losowe mikromodyfikacje
    rozbijające sygnatury vPDQ, TMK oraz audio fingerprinting.
    Stosuje flagi -bitexact, aby usunąć atomy kontenera i znaczniki kodera.
    Następnie usuwa wszelkie metadane (w tym C2PA/JUMBF) za pomocą ExifTool.
    """
    params = generate_random_params(mode=mode)
    vf, af = build_filter_chains(params)
    has_audio = await has_audio_stream(input_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-vf", vf,
    ]

    if has_audio:
        cmd.extend([
            "-af", af,
            "-c:a", "aac",
            "-b:a", "192k"
        ])
    else:
        cmd.extend(["-an"])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        "-movflags", "+faststart",
        str(output_path)
    ])

    logger.info(f"Running video uniquification (mode={mode}) on {input_path} -> {output_path}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace")[-300:]
            logger.error(f"FFmpeg failed with code {proc.returncode}: {err_text}")
            return False, None

        if not output_path.exists() or output_path.stat().st_size == 0:
            logger.error("FFmpeg output file does not exist or is empty.")
            return False, None

        # Czyścimy także wszelkie nowo utworzone metadane kontenera i C2PA za pomocą ExifTool
        await strip_metadata(output_path)

        logger.info(f"Successfully uniquified video: {output_path}")
        return True, params

    except asyncio.TimeoutError:
        logger.error(f"Timeout while uniquifying video {input_path}")
        return False, None
    except Exception as e:
        logger.error(f"Exception during video uniquification: {e}", exc_info=True)
        return False, None

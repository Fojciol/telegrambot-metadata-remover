import asyncio
import logging
import random
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
            "🛡️ <b>Modyfikacje percepcyjne (Bypass vPDQ/TMK/Audio):</b>",
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


def generate_random_params(mode: str = "mild") -> UniquifyParams:
    """Generuje losowy zestaw parametrów dla danego trybu unikalizacji."""
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

    # Drobny szum
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
    # Filtry wideo:
    # 1. crop do wyciętego środka i przeskalowanie do wielokrotności 2
    # 2. korekta gamma/kontrast/jasność
    # 3. ziarno/szum
    # 4. prędkość wideo (setpts)
    # 5. opcjonalnie odbicie lustrzane (hflip)
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

    # Filtry audio:
    # atempo musi odpowiadać prędkości wideo, aby zachować synchronizację A/V
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


async def uniquify_video(
    input_path: Path,
    output_path: Path,
    mode: str = "mild"
) -> Tuple[bool, Optional[UniquifyParams]]:
    """
    Przetwarza wideo za pomocą FFmpeg, aplikując losowe mikromodyfikacje
    rozbijające sygnatury vPDQ, TMK oraz audio fingerprinting.
    Następnie usuwa wszelkie metadane za pomocą ExifTool.
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

        # Czyścimy także wszelkie nowo utworzone metadane kontenera za pomocą ExifTool
        await strip_metadata(output_path)

        logger.info(f"Successfully uniquified video: {output_path}")
        return True, params

    except asyncio.TimeoutError:
        logger.error(f"Timeout while uniquifying video {input_path}")
        return False, None
    except Exception as e:
        logger.error(f"Exception during video uniquification: {e}", exc_info=True)
        return False, None

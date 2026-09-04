import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.video_uniquifier import (
    generate_random_params,
    build_filter_chains,
    uniquify_video,
    has_audio_stream
)


class TestVideoUniquifier(unittest.TestCase):

    def test_generate_random_params_mild(self):
        params = generate_random_params(mode="mild")
        self.assertEqual(params.mode, "mild")
        self.assertFalse(params.flip)
        self.assertTrue(0.970 <= params.crop_factor <= 0.990)
        self.assertTrue(params.noise_strength in (2, 3))
        self.assertTrue(0.95 <= params.speed <= 1.05)

        caption = params.format_telegram_caption()
        self.assertIn("Wideo zunikalizowane", caption)
        self.assertIn("Łagodna", caption)
        self.assertIn("Mikro-zoom", caption)
        self.assertIn("Wyłączone", caption)

    def test_generate_random_params_deep(self):
        params = generate_random_params(mode="deep")
        self.assertEqual(params.mode, "deep")
        self.assertTrue(params.flip)

        caption = params.format_telegram_caption()
        self.assertIn("Głęboka", caption)
        self.assertIn("hflip", caption)

    def test_build_filter_chains(self):
        mild_params = generate_random_params(mode="mild")
        vf_mild, af_mild = build_filter_chains(mild_params)

        self.assertIn("crop=", vf_mild)
        self.assertIn("scale=", vf_mild)
        self.assertIn("eq=", vf_mild)
        self.assertIn("noise=", vf_mild)
        self.assertIn("setpts=", vf_mild)
        self.assertNotIn("hflip", vf_mild)
        self.assertIn(f"atempo={mild_params.speed}", af_mild)

        deep_params = generate_random_params(mode="deep")
        vf_deep, af_deep = build_filter_chains(deep_params)
        self.assertIn("hflip", vf_deep)

    def test_uniquify_ffmpeg_end_to_end(self):
        # Sprawdzamy czy ffmpeg jest dostępny w systemie
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed on the system")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sample_in = tmp_path / "sample.mp4"
            sample_out = tmp_path / "sample_unique.mp4"

            # Generujemy 1-sekundowe wideo testowe z dźwiękiem
            gen_cmd = (
                f"ffmpeg -y -f lavfi -i testsrc=duration=1:size=160x120:rate=25 "
                f"-f lavfi -i sine=frequency=440:duration=1 "
                f"-c:v libx264 -preset ultrafast -c:a aac {sample_in} >/dev/null 2>&1"
            )
            res = os.system(gen_cmd)
            self.assertEqual(res, 0, "Failed to generate test video fixture")

            # Sprawdzamy has_audio_stream
            has_audio = asyncio.run(has_audio_stream(sample_in))
            self.assertTrue(has_audio)

            # Uruchamiamy unikalizację
            success, params = asyncio.run(uniquify_video(sample_in, sample_out, mode="mild"))
            self.assertTrue(success)
            self.assertIsNotNone(params)
            self.assertTrue(sample_out.exists())
            self.assertGreater(sample_out.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

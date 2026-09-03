import unittest
from pathlib import Path
from src.metadata import MetadataReport

try:
    from src.config import Settings
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


class TestBotComponents(unittest.TestCase):

    def test_settings_allowed_user_ids_parsing(self):
        if not HAS_PYDANTIC:
            self.skipTest("pydantic-settings is not installed in local environment (runs in Docker)")

        # Test comma-separated string
        s1 = Settings(bot_token="fake_token", allowed_user_ids="12345, 67890, -100123")
        self.assertEqual(s1.allowed_user_ids, {12345, 67890, -100123})
        self.assertEqual(s1.max_file_size_mb, 30)

        # Test empty string
        s2 = Settings(bot_token="fake_token", allowed_user_ids="")
        self.assertEqual(s2.allowed_user_ids, set())

        # Test list of ints
        s3 = Settings(bot_token="fake_token", allowed_user_ids=[111, 222])
        self.assertEqual(s3.allowed_user_ids, {111, 222})

    def test_metadata_report_formatting_with_data(self):
        report = MetadataReport(
            gps="52.2297 N, 21.0122 E",
            device="Apple iPhone 15 Pro",
            date="2024:05:10 14:32:00",
            software="iOS 17.4",
            author="Jan Kowalski",
            total_tags_found=24
        )
        self.assertTrue(report.has_sensitive_data)
        formatted = report.format_telegram_message()

        self.assertIn("Lokalizacja GPS", formatted)
        self.assertIn("52.2297 N, 21.0122 E", formatted)
        self.assertIn("Apple iPhone 15 Pro", formatted)
        self.assertIn("Jan Kowalski", formatted)
        self.assertIn("24", formatted)

    def test_metadata_report_formatting_clean_file(self):
        report = MetadataReport(total_tags_found=0)
        self.assertFalse(report.has_sensitive_data)
        formatted = report.format_telegram_message()

        self.assertIn("nie wykryto żadnych ukrytych metadanych", formatted)


if __name__ == "__main__":
    unittest.main()

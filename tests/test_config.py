import unittest

from drama_cut.config import Settings


class ConfigTest(unittest.TestCase):
    def test_missing_api_key_message(self):
        settings = Settings(ark_api_key=None, ark_base_url="https://example.com", ark_model_name="model")
        with self.assertRaisesRegex(RuntimeError, "ARK_API_KEY"):
            settings.require_ark_api_key()


if __name__ == "__main__":
    unittest.main()

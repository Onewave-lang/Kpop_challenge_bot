import os
import sys
from pathlib import Path
import unittest

# The main application expects certain environment variables to be set at import
# time. Provide dummy values and ensure project root is on sys.path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

from app import norm_group_key


class NormGroupKeyTest(unittest.TestCase):
    def test_collapses_internal_whitespace(self):
        self.assertEqual(norm_group_key("  Red   Velvet "), "red velvet")
        self.assertEqual(norm_group_key("BLACKPINK"), "blackpink")


if __name__ == "__main__":
    unittest.main()

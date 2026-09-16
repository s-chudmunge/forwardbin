"""
Unit tests for ForwardBin core modules (CI/CD verification).
All external network dependencies (OpenRouter, Resend) are isolated/mocked.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from forwardbin.config import load_config, DEFAULT_CONFIG
from forwardbin.calendar_sync import find_next_available_slot
from forwardbin.db import init_db


class TestForwardBin(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_default_config_structure(self):
        cfg = load_config()
        self.assertIn("preferred_hours", cfg)
        self.assertIn("preferred_categories", cfg)
        self.assertEqual(cfg["preferred_hours"]["start"], 9)
        self.assertEqual(cfg["preferred_hours"]["end"], 22)

    def test_env_override_precedence(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-override-key", "USER_EMAIL": "test@ci.cd"}):
            cfg = load_config()
            self.assertEqual(cfg["openrouter_api_key"], "test-override-key")
            self.assertEqual(cfg["user_email"], "test@ci.cd")

    def test_slot_finder_basic(self):
        start, end = find_next_available_slot(duration_minutes=30, preferred_window="anytime")
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertGreater(end, start)


if __name__ == "__main__":
    unittest.main()

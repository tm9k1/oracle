"""
Unit tests for the Oracle onboarding wizard (scripts/onboard.py).
"""
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from onboard import (
    init_starter_kb,
    update_config_file,
    setup_env_credentials,
    setup_knowledge_base,
    setup_backend,
)
import onboard


class TestOnboard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Mock global paths in onboard module
        self.orig_config_file = onboard.CONFIG_FILE
        self.orig_env_file = onboard.ENV_FILE
        self.mock_config_file = self.temp_path / "config.json"
        self.mock_env_file = self.temp_path / ".env"
        onboard.CONFIG_FILE = self.mock_config_file
        onboard.ENV_FILE = self.mock_env_file

    def tearDown(self):
        onboard.CONFIG_FILE = self.orig_config_file
        onboard.ENV_FILE = self.orig_env_file
        self.temp_dir.cleanup()

    def test_init_starter_kb(self):
        target = self.temp_path / "my_notes"
        init_starter_kb(target)

        self.assertTrue(target.exists())
        self.assertTrue((target / "README.md").exists())
        self.assertTrue((target / "DISPATCH.md").exists())
        self.assertTrue((target / "entities" / "me.md").exists())
        self.assertTrue((target / "mind" / "preferences.md").exists())

    def test_update_config_file(self):
        vault_path = self.temp_path / "vault"
        update_config_file(
            vault_path=vault_path,
            vault_name="My Second Brain",
            backend="agy",
            model="gemini-3.8-flash-high",
            user_name="Alice",
            bot_name="Oracle",
        )

        self.assertTrue(self.mock_config_file.exists())
        cfg = json.loads(self.mock_config_file.read_text(encoding="utf-8"))
        self.assertEqual(cfg["kb"]["vault_path"], str(vault_path))
        self.assertEqual(cfg["kb"]["vault_name"], "My Second Brain")
        self.assertEqual(cfg["ai"]["backend"], "agy")
        self.assertEqual(cfg["ai"]["model"], "gemini-3.8-flash-high")
        self.assertEqual(cfg["user"]["name"], "Alice")
        self.assertEqual(cfg["discord"]["bot_name"], "Oracle")

    def test_setup_env_credentials(self):
        setup_env_credentials(token="mock_discord_token_12345", interactive=False)
        self.assertTrue(self.mock_env_file.exists())
        content = self.mock_env_file.read_text(encoding="utf-8")
        self.assertIn("DISCORD_TOKEN=mock_discord_token_12345", content)

    def test_setup_knowledge_base_non_interactive(self):
        custom_vault = self.temp_path / "custom_notes"
        vpath, vname = setup_knowledge_base(
            vault_path_str=str(custom_vault),
            vault_name="Custom Notes",
            interactive=False,
            init_template=True,
        )
        self.assertEqual(vpath, custom_vault.resolve())
        self.assertEqual(vname, "Custom Notes")
        self.assertTrue(custom_vault.exists())
        self.assertTrue((custom_vault / "README.md").exists())

    def test_setup_backend(self):
        backend, model = setup_backend(
            chosen_backend="agy",
            chosen_model="gemini-3.8-flash-high",
            interactive=False,
        )
        self.assertEqual(backend, "agy")
        self.assertEqual(model, "gemini-3.8-flash-high")


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawPluginTests(unittest.TestCase):
    def test_manifest_is_valid_json(self) -> None:
        manifest = ROOT / "openclaw.plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "unolock-agent")
        self.assertEqual(data["skills"], ["skills"])

    def test_plugin_uses_shared_skill_directory(self) -> None:
        primary = ROOT / "skills" / "unolock-agent-access" / "SKILL.md"
        self.assertTrue(primary.exists())

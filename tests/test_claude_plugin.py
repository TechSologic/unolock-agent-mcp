from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ClaudePluginTests(unittest.TestCase):
    def test_manifest_is_valid_json(self) -> None:
        manifest = ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "unolock-agent")
        self.assertEqual(data["version"], "0.1.53")

    def test_shared_skill_exists(self) -> None:
        skill = ROOT / "skills" / "unolock-agent-access" / "SKILL.md"
        self.assertTrue(skill.exists())

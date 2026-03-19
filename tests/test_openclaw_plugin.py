from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenClawPluginTests(unittest.TestCase):
    def test_manifest_is_valid_json(self) -> None:
        manifest = ROOT / "openclaw-plugin" / "openclaw.plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "unolock-agent-access")

    def test_plugin_skill_matches_primary_skill_frontmatter(self) -> None:
        primary = ROOT / "skills" / "unolock-agent-access" / "SKILL.md"
        plugin = ROOT / "openclaw-plugin" / "skills" / "unolock-agent-access" / "SKILL.md"
        self.assertEqual(
            primary.read_text(encoding="utf-8").splitlines()[0:6],
            plugin.read_text(encoding="utf-8").splitlines()[0:6],
        )

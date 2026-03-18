from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from unolock_mcp.config import default_config_path, default_state_dir, derive_transparency_origin, load_config_file, load_unolock_config, resolve_unolock_config


class UnoLockConfigTest(unittest.TestCase):
    def test_default_state_dir_uses_unolock_config_dir_override(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_CONFIG_DIR": "/tmp/unolock-config-dir"}, clear=False):
            self.assertEqual(default_state_dir(), Path("/tmp/unolock-config-dir"))

    def test_default_state_dir_defaults_to_windows_localappdata(self) -> None:
        with patch("unolock_mcp.config.os.name", "nt"):
            with patch("unolock_mcp.config.sys.platform", "win32"):
                with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\mike\AppData\Local"}, clear=True):
                    with patch("unolock_mcp.config.Path", PureWindowsPath):
                        self.assertEqual(
                            default_state_dir(),
                            PureWindowsPath(r"C:\Users\mike\AppData\Local") / "unolock-agent-mcp",
                        )

    def test_default_state_dir_defaults_to_macos_application_support(self) -> None:
        with patch("unolock_mcp.config.os.name", "posix"):
            with patch("unolock_mcp.config.sys.platform", "darwin"):
                with patch.dict(os.environ, {}, clear=True):
                    with patch("pathlib.Path.home", return_value=Path("/Users/mike")):
                        self.assertEqual(
                            default_state_dir(),
                            Path("/Users/mike/Library/Application Support/unolock-agent-mcp"),
                        )

    def test_default_config_path_uses_platform_state_dir(self) -> None:
        with patch("unolock_mcp.config.default_state_dir", return_value=Path("/tmp/unolock-state")):
            self.assertEqual(default_config_path(), Path("/tmp/unolock-state/config.json"))

    def test_load_config_file_reads_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "https://example.test",
                        "transparency_origin": "https://safe.example.test",
                        "app_version": "1.2.3",
                        "signing_public_key_b64": "abc123",
                    }
                ),
                encoding="utf8",
            )

            loaded = load_config_file(config_path)

            self.assertEqual(loaded["base_url"], "https://example.test")
            self.assertEqual(loaded["transparency_origin"], "https://safe.example.test")
            self.assertEqual(loaded["app_version"], "1.2.3")
            self.assertEqual(loaded["signing_public_key_b64"], "abc123")

    def test_resolve_unolock_config_uses_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "https://file.example",
                        "transparency_origin": "https://safe.file.example",
                        "app_version": "9.9.9",
                        "signing_public_key_b64": "file-key",
                    }
                ),
                encoding="utf8",
            )

            old_config_path = os.environ.get("UNOLOCK_CONFIG_FILE")
            os.environ["UNOLOCK_CONFIG_FILE"] = str(config_path)
            try:
                resolved = resolve_unolock_config()
            finally:
                if old_config_path is None:
                    os.environ.pop("UNOLOCK_CONFIG_FILE", None)
                else:
                    os.environ["UNOLOCK_CONFIG_FILE"] = old_config_path

            self.assertEqual(resolved.base_url, "https://file.example")
            self.assertEqual(resolved.transparency_origin, "https://safe.file.example")
            self.assertEqual(resolved.app_version, "9.9.9")
            self.assertEqual(resolved.signing_public_key_b64, "file-key")
            self.assertTrue(resolved.sources["app_version"].startswith("file:"))
            self.assertTrue(resolved.sources["signing_public_key_b64"].startswith("file:"))

    def test_resolve_unolock_config_prefers_env_over_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "base_url": "https://file.example",
                        "app_version": "9.9.9",
                        "signing_public_key_b64": "file-key",
                    }
                ),
                encoding="utf8",
            )

            old_values = {
                "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
                "UNOLOCK_BASE_URL": os.environ.get("UNOLOCK_BASE_URL"),
                "UNOLOCK_TRANSPARENCY_ORIGIN": os.environ.get("UNOLOCK_TRANSPARENCY_ORIGIN"),
                "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
                "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            }
            os.environ["UNOLOCK_CONFIG_FILE"] = str(config_path)
            os.environ["UNOLOCK_BASE_URL"] = "https://env.example"
            os.environ["UNOLOCK_TRANSPARENCY_ORIGIN"] = "https://safe.env.example"
            os.environ["UNOLOCK_APP_VERSION"] = "2.0.0"
            os.environ["UNOLOCK_SIGNING_PUBLIC_KEY"] = "env-key"
            try:
                resolved = resolve_unolock_config()
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

            self.assertEqual(resolved.base_url, "https://env.example")
            self.assertEqual(resolved.transparency_origin, "https://safe.env.example")
            self.assertEqual(resolved.app_version, "2.0.0")
            self.assertEqual(resolved.signing_public_key_b64, "env-key")
            self.assertEqual(resolved.sources["app_version"], "env:UNOLOCK_APP_VERSION")
            self.assertEqual(resolved.sources["signing_public_key_b64"], "env:UNOLOCK_SIGNING_PUBLIC_KEY")

    def test_resolve_unolock_config_reports_incomplete_when_missing_required_values(self) -> None:
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            resolved = resolve_unolock_config(base_url="https://arg.example")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(resolved.base_url, "https://arg.example")
        self.assertEqual(resolved.transparency_origin, "https://arg.example")
        self.assertEqual(resolved.app_version, "0.20.21")
        self.assertIsNone(resolved.signing_public_key_b64)
        self.assertFalse(resolved.is_complete())
        self.assertEqual(resolved.sources["app_version"], "bundled-default")

    def test_derive_transparency_origin_removes_api_prefix_for_hosted_urls(self) -> None:
        self.assertEqual(derive_transparency_origin("https://api.safe.unolock.com"), "https://safe.unolock.com")
        self.assertEqual(derive_transparency_origin("https://safe.unolock.com"), "https://safe.unolock.com")
        self.assertIsNone(derive_transparency_origin("http://127.0.0.1:3000"))

    def test_load_unolock_config_uses_generic_runtime_metadata_error(self) -> None:
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            with self.assertRaisesRegex(
                ValueError,
                "UnoLock runtime metadata is not resolved yet\\. Submit a UnoLock agent key connection URL from the target Safe first, or configure a custom deployment override\\.",
            ):
                load_unolock_config(base_url="https://arg.example")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @patch("unolock_mcp.config.fetch_hosted_client_metadata")
    def test_resolve_unolock_config_uses_hosted_client_metadata_fallback(self, fetch_hosted_client_metadata) -> None:
        fetch_hosted_client_metadata.return_value = {
            "app_version": "0.20.21",
            "signing_public_key_b64": "hosted-key",
        }
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            resolved = resolve_unolock_config(base_url="https://api.safe.unolock.com")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(resolved.transparency_origin, "https://safe.unolock.com")
        self.assertEqual(resolved.app_version, "0.20.21")
        self.assertEqual(resolved.signing_public_key_b64, "hosted-key")
        self.assertEqual(resolved.sources["app_version"], "hosted-client-metadata:https://safe.unolock.com")
        self.assertEqual(
            resolved.sources["signing_public_key_b64"],
            "hosted-client-metadata:https://safe.unolock.com",
        )

    @patch("unolock_mcp.config.fetch_hosted_client_metadata")
    def test_resolve_unolock_config_fetches_hosted_metadata_for_derived_custom_host(
        self,
        fetch_hosted_client_metadata,
    ) -> None:
        fetch_hosted_client_metadata.return_value = {
            "app_version": "0.20.21-custom",
            "signing_public_key_b64": "custom-hosted-key",
        }
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            resolved = resolve_unolock_config(base_url="https://api.safe.test.1two.be")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        fetch_hosted_client_metadata.assert_called_once_with("https://safe.test.1two.be")
        self.assertEqual(resolved.transparency_origin, "https://safe.test.1two.be")
        self.assertEqual(resolved.app_version, "0.20.21-custom")
        self.assertEqual(resolved.signing_public_key_b64, "custom-hosted-key")
        self.assertEqual(resolved.sources["app_version"], "hosted-client-metadata:https://safe.test.1two.be")
        self.assertEqual(
            resolved.sources["signing_public_key_b64"],
            "hosted-client-metadata:https://safe.test.1two.be",
        )

    @patch("unolock_mcp.config.fetch_transparency_metadata")
    @patch("unolock_mcp.config.fetch_hosted_client_metadata")
    def test_resolve_unolock_config_falls_back_to_transparency_bundle(
        self,
        fetch_hosted_client_metadata,
        fetch_transparency_metadata,
    ) -> None:
        fetch_hosted_client_metadata.side_effect = OSError("missing unolock-client.json")
        fetch_transparency_metadata.return_value = {
            "app_version": "0.20.21-20260309",
            "signing_public_key_b64": "transparency-key",
        }
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            resolved = resolve_unolock_config(base_url="https://api.safe.unolock.com")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(resolved.app_version, "0.20.21-20260309")
        self.assertEqual(resolved.signing_public_key_b64, "transparency-key")
        self.assertEqual(resolved.sources["app_version"], "hosted-transparency:https://safe.unolock.com")
        self.assertEqual(
            resolved.sources["signing_public_key_b64"],
            "hosted-transparency:https://safe.unolock.com",
        )

    @patch("unolock_mcp.config.fetch_local_bundle_metadata")
    def test_resolve_unolock_config_uses_local_bundle_metadata_for_local_dev(self, fetch_local_bundle_metadata) -> None:
        fetch_local_bundle_metadata.return_value = {
            "app_version": "0.20.21",
            "signing_public_key_b64": "local-key",
        }
        old_values = {
            "UNOLOCK_CONFIG_FILE": os.environ.get("UNOLOCK_CONFIG_FILE"),
            "UNOLOCK_APP_VERSION": os.environ.get("UNOLOCK_APP_VERSION"),
            "UNOLOCK_SIGNING_PUBLIC_KEY": os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"),
            "UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY": os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"),
        }
        os.environ["UNOLOCK_CONFIG_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-unolock-config.json")
        os.environ["UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY"] = "1"
        os.environ.pop("UNOLOCK_APP_VERSION", None)
        os.environ.pop("UNOLOCK_SIGNING_PUBLIC_KEY", None)
        try:
            resolved = resolve_unolock_config(
                base_url="http://127.0.0.1:3000",
                transparency_origin="http://localhost:4200",
            )
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(resolved.app_version, "0.20.21")
        self.assertEqual(resolved.signing_public_key_b64, "local-key")
        self.assertEqual(resolved.sources["app_version"], "local-dev-bundle:http://localhost:4200")
        self.assertEqual(
            resolved.sources["signing_public_key_b64"],
            "local-dev-bundle:http://localhost:4200",
        )


if __name__ == "__main__":
    unittest.main()

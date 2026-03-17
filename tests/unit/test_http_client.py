from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from unolock_mcp import __version__ as MCP_VERSION
from unolock_mcp.transport.http_client import HttpClient


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class HttpClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = HttpClient("https://api.example.test/", "0.20.21")

    def test_default_headers_include_app_and_mcp_versions(self) -> None:
        self.assertEqual(self.client.default_headers["x-app-version"], "0.20.21")
        self.assertEqual(self.client.default_headers["x-unolock-agent-mcp-version"], MCP_VERSION)
        self.assertEqual(self.client.default_headers["User-Agent"], f"unolock-agent-mcp/{MCP_VERSION}")
        self.assertEqual(self.client.default_headers["Content-Type"], "application/json")

    @patch("urllib.request.urlopen")
    def test_get_json_uses_trimmed_base_url_and_default_headers(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(json.dumps({"ok": True}).encode("utf8"))

        result = self.client.get_json("/start?type=access")

        self.assertEqual(result, {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.test/start?type=access")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.headers["X-app-version"], "0.20.21")

    @patch("urllib.request.urlopen")
    def test_post_json_serializes_payload(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(json.dumps({"done": True}).encode("utf8"))

        result = self.client.post_json("/start", {"state": "abc"})

        self.assertEqual(result, {"done": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.test/start")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf8")), {"state": "abc"})

    @patch("urllib.request.urlopen")
    def test_get_text_with_headers_absolute_returns_body_and_headers(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(b"payload", headers={"ETag": '"etag-1"'})

        body, headers = self.client.get_text_with_headers_absolute("https://download.example/file")

        self.assertEqual(body, "payload")
        self.assertEqual(headers["ETag"], '"etag-1"')

    @patch("urllib.request.urlopen")
    def test_get_bytes_with_headers_absolute_returns_body_and_headers(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(b"\x00\x01payload", headers={"Content-Length": "9"})

        body, headers = self.client.get_bytes_with_headers_absolute(
            "https://download.example/file",
            headers={"Range": "bytes=0-8"},
        )

        self.assertEqual(body, b"\x00\x01payload")
        self.assertEqual(headers["Content-Length"], "9")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Range"], "bytes=0-8")

    @patch("urllib.request.urlopen")
    def test_head_absolute_uses_custom_headers(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(b"", status=200, headers={"ETag": '"etag-2"'})

        result = self.client.head_absolute("https://download.example/file", headers={"If-Match": '"etag-1"'})

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["headers"]["ETag"], '"etag-2"')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(request.headers["If-match"], '"etag-1"')

    @patch("urllib.request.urlopen")
    def test_post_multipart_absolute_builds_form_body(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse(b"", status=204, headers={"X-Test": "ok"})

        result = self.client.post_multipart_absolute(
            "https://upload.example/file",
            fields={"key": "archive-1", "policy": "abc"},
            file_field="file",
            file_name="archive.json",
            file_bytes=b"hello world",
            headers={"x-amz-checksum-sha256": "checksum"},
        )

        self.assertEqual(result["status"], 204)
        self.assertEqual(result["headers"]["X-Test"], "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["X-amz-checksum-sha256"], "checksum")
        self.assertIn("multipart/form-data; boundary=", request.headers["Content-type"])
        body = request.data
        self.assertIn(b'Content-Disposition: form-data; name="key"', body)
        self.assertIn(b"archive-1", body)
        self.assertIn(b'Content-Disposition: form-data; name="file"; filename="archive.json"', body)
        self.assertIn(b"hello world", body)


if __name__ == "__main__":
    unittest.main()

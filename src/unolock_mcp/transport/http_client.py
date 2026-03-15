from __future__ import annotations

import uuid
import json
import urllib.request
from typing import Any

from unolock_mcp import __version__ as MCP_VERSION


class HttpClient:
    def __init__(self, base_url: str, app_version: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._app_version = app_version

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "x-app-version": self._app_version,
            "x-unolock-agent-mcp-version": MCP_VERSION,
            "User-Agent": f"unolock-agent-mcp/{MCP_VERSION}",
            "Content-Type": "application/json",
        }

    def get_json(self, path_with_query: str) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}{path_with_query}",
            headers=self.default_headers,
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf8"))

    def post_json(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode("utf8"),
            headers=self.default_headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf8"))

    def get_text_absolute(self, url: str) -> str:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf8")

    def get_text_with_headers_absolute(self, url: str) -> tuple[str, dict[str, str]]:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf8"), dict(response.headers.items())

    def put_bytes_absolute(self, url: str, body: bytes, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request_headers = dict(headers or {})
        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": response.read(),
            }

    def head_absolute(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="HEAD")
        with urllib.request.urlopen(request, timeout=30) as response:
            return {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": response.read(),
            }

    def post_multipart_absolute(
        self,
        url: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        file_content_type: str = "application/octet-stream",
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        boundary = f"----UnoLockAgentMcp{uuid.uuid4().hex}"
        request_headers = dict(headers or {})
        request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf8"))
            body.extend(value.encode("utf8"))
            body.extend(b"\r\n")

        body.extend(f"--{boundary}\r\n".encode("utf8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                f"Content-Type: {file_content_type}\r\n\r\n"
            ).encode("utf8")
        )
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf8"))

        request = urllib.request.Request(
            url,
            data=bytes(body),
            headers=request_headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": response.read(),
            }

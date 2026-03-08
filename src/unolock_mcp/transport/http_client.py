from __future__ import annotations

import json
import urllib.request


class HttpClient:
    def __init__(self, base_url: str, app_version: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._app_version = app_version

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "x-app-version": self._app_version,
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

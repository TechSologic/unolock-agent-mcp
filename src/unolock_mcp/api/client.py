from __future__ import annotations

from typing import Any

from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.session_store import SessionStore


class UnoLockApiClient:
    def __init__(self, flow_client: UnoLockFlowClient, session_store: SessionStore) -> None:
        self._flow_client = flow_client
        self._session_store = session_store

    def call_action(
        self,
        session_id: str,
        *,
        action: str,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> dict[str, Any]:
        session = self._session_store.get(session_id)
        updated_session, callback = self._flow_client.call_api(
            session,
            action=action,
            request=request,
            result=result,
            reason=reason,
            message=message,
        )
        self._session_store.put(updated_session)
        return {
            "session": updated_session.summary(),
            "callback": callback.to_payload(),
        }

    def get_spaces(self, session_id: str) -> dict[str, Any]:
        return self.call_action(session_id, action="GetSpaces")

    def get_archives(self, session_id: str) -> dict[str, Any]:
        return self.call_action(session_id, action="GetArchives")

    def get_regional_download_url(self, session_id: str, archive_id: str) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="GetRegionalDownloadUrl",
            request={"archiveID": archive_id},
        )

    def get_download_url(self, session_id: str, archive_id: str) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="GetDownloadUrl",
            request={"archiveID": archive_id},
        )

    def update_archive(self, session_id: str, archive: dict[str, Any]) -> dict[str, Any]:
        return self.call_action(session_id, action="UpdateArchive", request=archive)

    def get_upload_put_url(
        self,
        session_id: str,
        archive_id: str,
        md5_b64: str,
        current_etag: str | None = None,
        new_etag: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"archiveID": archive_id, "md5": md5_b64}
        if current_etag:
            request["currentEtag"] = current_etag
        if new_etag:
            request["newEtag"] = new_etag
        return self.call_action(session_id, action="GetUploadPutUrl", request=request)

    @property
    def http_client(self):
        return self._flow_client.http_client

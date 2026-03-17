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

    def create_archive(self, session_id: str, archive: dict[str, Any]) -> dict[str, Any]:
        return self.call_action(session_id, action="CreateArchive", request=archive)

    def delete_archive(self, session_id: str, archive_id: str) -> dict[str, Any]:
        return self.call_action(session_id, action="DeleteArchive", request=archive_id)

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

    def get_upload_post_object(self, session_id: str, archive_id: str) -> dict[str, Any]:
        return self.call_action(session_id, action="GetUploadPostObject", request=archive_id)

    def init_archive_upload(self, session_id: str, archive_id: str, md5_b64: str) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="InitArchiveUpload",
            request={"archiveID": archive_id, "md5": md5_b64},
        )

    def get_archive_upload_url(
        self,
        session_id: str,
        *,
        archive_id: str,
        part_number: int,
        upload_id: str,
        md5_b64: str,
    ) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="GetArchiveUploadUrl",
            request={
                "archiveID": archive_id,
                "partNumber": part_number,
                "uploadId": upload_id,
                "md5": md5_b64,
            },
        )

    def complete_archive_upload(
        self,
        session_id: str,
        *,
        archive_id: str,
        upload_id: str,
        metadata: str,
        parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="CompleteArchiveUpload",
            request={
                "archiveID": archive_id,
                "metadata": metadata,
                "uploadId": upload_id,
                "parts": parts,
            },
        )

    def abort_multipart_upload(self, session_id: str, *, archive_id: str, upload_id: str) -> dict[str, Any]:
        return self.call_action(
            session_id,
            action="AbortMultipartUpload",
            request={"archiveID": archive_id, "uploadId": upload_id},
        )

    @property
    def http_client(self):
        return self._flow_client.http_client

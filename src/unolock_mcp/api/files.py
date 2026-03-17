from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from unolock_mcp.api.records import _UnoLockRecordsBase


class UnoLockReadonlyFilesClient(_UnoLockRecordsBase):
    def list_files(self, session_id: str, *, space_id: int | None = None) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = self._load_archives(session_id, keyring)
        files: list[dict[str, Any]] = []

        for archive in archives:
            if archive.get("t") != "Cloud":
                continue
            projected = self._project_cloud_file(archive, spaces, session_id=session_id)
            if space_id is not None and projected["space_id"] != space_id:
                continue
            files.append(projected)

        files.sort(key=lambda item: (item["space_id"], item["name"].lower(), item["archive_id"]))
        return {
            "space_id_filter": space_id,
            "count": len(files),
            "files": files,
        }

    def get_file(self, session_id: str, archive_id: str) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archive = self._require_cloud_archive(session_id, archive_id, keyring=keyring)
        return self._project_cloud_file(archive, spaces, session_id=session_id)

    def download_file(
        self,
        session_id: str,
        *,
        archive_id: str,
        output_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archive = self._require_cloud_archive(session_id, archive_id, keyring=keyring)
        projected = self._project_cloud_file(archive, spaces, session_id=session_id)

        destination = Path(output_path).expanduser()
        if destination.exists() and not overwrite:
            raise ValueError("invalid_input: output_path already exists. Set overwrite=true or choose a different path.")
        if destination.exists() and destination.is_dir():
            raise ValueError("invalid_input: output_path must point to a file, not a directory.")
        if not destination.parent.exists():
            raise ValueError("invalid_input: output_path parent directory does not exist.")

        signed_url = self._extract_result(
            self._api_client.get_download_url(session_id, archive_id),
            expected_type="GetDownloadUrl",
        )
        if not isinstance(signed_url, str) or not signed_url:
            raise ValueError("operation_failed: Download URL was not returned for this file.")

        metadata = archive.get("m") if isinstance(archive.get("m"), dict) else {}
        kek = metadata.get("kek") if isinstance(metadata.get("kek"), str) else None
        part_sizes = self._cloud_part_sizes(archive)

        bytes_written = 0
        try:
            with destination.open("wb") as handle:
                offset = 0
                for part_index, encrypted_size in enumerate(part_sizes):
                    range_header = {"Range": f"bytes={offset}-{offset + encrypted_size - 1}"}
                    encrypted_chunk = self._api_client.http_client.get_bytes_absolute(signed_url, headers=range_header)
                    plaintext_chunk = keyring.decrypt_bytes_with_kek(
                        encrypted_chunk,
                        archive_id=archive_id,
                        sid=self._coerce_sid(archive.get("sid")),
                        kek=kek,
                    )
                    handle.write(plaintext_chunk)
                    bytes_written += len(plaintext_chunk)
                    offset += encrypted_size
        except Exception:
            try:
                destination.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        return {
            "ok": True,
            "file": projected,
            "output_path": str(destination),
            "bytes_written": bytes_written,
        }

    def _project_cloud_file(
        self,
        archive: dict[str, Any],
        spaces: dict[int, dict[str, Any]],
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = self._coerce_sid(archive.get("sid"))
        metadata = archive.get("m") if isinstance(archive.get("m"), dict) else {}
        session_can_write = self._session_can_write(session_id) if session_id else False
        return {
            "archive_id": str(archive.get("id", "")),
            "space_id": sid,
            "space_name": str(metadata.get("spaceName", spaces.get(sid, {}).get("spaceName", ""))),
            "kind": "file",
            "name": str(metadata.get("name", "")),
            "mime_type": str(metadata.get("type", "application/octet-stream")),
            "size": self._coerce_positive_int(archive.get("fs")) or 0,
            "encrypted_size": self._coerce_positive_int(archive.get("s")) or 0,
            "part_count": len(self._cloud_part_sizes(archive)),
            "writable": session_can_write,
            "allowed_operations": self._file_allowed_operations(),
        }

    def _file_allowed_operations(self) -> list[str]:
        return ["get_file", "download_file"]

    def _require_cloud_archive(
        self,
        session_id: str,
        archive_id: str,
        *,
        keyring,
    ) -> dict[str, Any]:
        for archive in self._load_archives(session_id, keyring):
            if str(archive.get("id", "")) != archive_id:
                continue
            if archive.get("t") != "Cloud":
                raise ValueError("operation_not_allowed: Only Cloud files are supported by the MCP.")
            return archive
        raise ValueError("record_not_found: Cloud file not found for archive_id.")

    def _cloud_part_sizes(self, archive: dict[str, Any]) -> list[int]:
        raw_sizes = archive.get("p")
        if isinstance(raw_sizes, list):
            sizes = [int(size) for size in raw_sizes if self._coerce_positive_int(size)]
            if sizes:
                return sizes
        encrypted_size = self._coerce_positive_int(archive.get("s"))
        return [encrypted_size] if encrypted_size else []


class UnoLockWritableFilesClient(UnoLockReadonlyFilesClient):
    CHUNK_SIZE = 10 * 1024 * 1024

    def upload_file(
        self,
        session_id: str,
        *,
        space_id: int,
        local_path: str,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_session_writable(session_id)

        source_path = Path(local_path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("invalid_input: local_path must point to an existing file.")
        file_size = source_path.stat().st_size
        if file_size <= 0:
            raise ValueError("invalid_input: Empty files are not supported for Cloud upload yet.")

        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = self._load_archives(session_id, keyring)
        location_id = self._resolve_cloud_upload_location(space_id, archives)
        if not location_id:
            raise ValueError("operation_not_allowed: No Cloud-capable location could be resolved for the requested space.")

        file_name = name.strip() if isinstance(name, str) and name.strip() else source_path.name
        resolved_mime = mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else None
        if not resolved_mime:
            resolved_mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        metadata = {"name": file_name, "type": resolved_mime}
        archive_id = ""
        upload_id = ""
        upload_completed = False

        try:
            encrypted_metadata = keyring.encrypt_string(json.dumps(metadata, separators=(",", ":")), sid=space_id)
            created_archive = self._extract_result(
                self._api_client.create_archive(
                    session_id,
                    {
                        "t": "Cloud",
                        "m": encrypted_metadata,
                        "l": location_id,
                        "fs": file_size,
                        "sid": space_id,
                    },
                ),
                expected_type="CreateArchive",
            )
            if not isinstance(created_archive, dict) or not created_archive.get("id"):
                raise ValueError("operation_failed: CreateArchive did not return a new Cloud archive.")
            archive_id = str(created_archive["id"])
            archive_metadata = dict(metadata)
            parts: list[dict[str, Any]] = []

            with source_path.open("rb") as handle:
                part_number = 1
                while True:
                    plaintext_chunk = handle.read(self.CHUNK_SIZE)
                    if not plaintext_chunk:
                        break
                    encrypted_chunk, next_kek = keyring.encrypt_bytes_with_kek(
                        plaintext_chunk,
                        archive_id=archive_id,
                        sid=space_id,
                        kek=archive_metadata.get("kek"),
                    )
                    if next_kek != archive_metadata.get("kek"):
                        archive_metadata["kek"] = next_kek

                    md5_b64 = base64.b64encode(hashlib.md5(encrypted_chunk).digest()).decode("ascii")
                    if part_number == 1:
                        init_result = self._extract_result(
                            self._api_client.init_archive_upload(session_id, archive_id, md5_b64),
                            expected_type="InitArchiveUpload",
                        )
                        if not isinstance(init_result, dict):
                            raise ValueError("operation_failed: InitArchiveUpload did not return upload details.")
                        upload_id = str(init_result.get("uploadId", ""))
                        signed_url = init_result.get("signedUrl")
                    else:
                        signed_url = self._extract_result(
                            self._api_client.get_archive_upload_url(
                                session_id,
                                archive_id=archive_id,
                                part_number=part_number,
                                upload_id=upload_id,
                                md5_b64=md5_b64,
                            ),
                            expected_type="GetArchiveUploadUrl",
                        )
                    if not isinstance(signed_url, str) or not signed_url:
                        raise ValueError("operation_failed: Upload URL was not returned for a Cloud file part.")
                    result = self._api_client.http_client.put_bytes_absolute(
                        signed_url,
                        encrypted_chunk,
                        headers={"Content-MD5": md5_b64},
                    )
                    etag = result["headers"].get("ETag") or result["headers"].get("etag")
                    parts.append(
                        {
                            "PartNumber": part_number,
                            "ETag": etag,
                            "size": len(encrypted_chunk),
                        }
                    )
                    part_number += 1

            complete_result = self._extract_result(
                self._api_client.complete_archive_upload(
                    session_id,
                    archive_id=archive_id,
                    upload_id=upload_id,
                    metadata=keyring.encrypt_string(json.dumps(archive_metadata, separators=(",", ":")), sid=space_id),
                    parts=parts,
                ),
                expected_type="CompleteArchiveUpload",
            )
            if isinstance(complete_result, dict) and complete_result.get("result") not in {None, "SUCCESS"}:
                raise ValueError("operation_failed: CompleteArchiveUpload did not report success.")
            upload_completed = True
            return {
                "ok": True,
                "file": self.get_file(session_id, archive_id),
            }
        except Exception:
            if archive_id and upload_id and not upload_completed:
                try:
                    self._extract_result(
                        self._api_client.abort_multipart_upload(
                            session_id,
                            archive_id=archive_id,
                            upload_id=upload_id,
                        ),
                        expected_type="AbortMultipartUpload",
                    )
                except Exception:
                    pass
            if archive_id and not upload_completed:
                try:
                    self._extract_result(
                        self._api_client.delete_archive(session_id, archive_id),
                        expected_type="DeleteArchive",
                    )
                except Exception:
                    pass
            raise

    def _resolve_cloud_upload_location(self, space_id: int, archives: list[dict[str, Any]]) -> str | None:
        preferred_types = ("Records", "Cloud")
        for archive_type in preferred_types:
            for archive in archives:
                if archive.get("t") != archive_type:
                    continue
                if self._coerce_sid(archive.get("sid")) != space_id:
                    continue
                location_id = str(archive.get("l", "")).strip()
                if location_id and location_id not in {"Local"}:
                    return location_id
        return None

    def _ensure_session_writable(self, session_id: str) -> None:
        auth_context = self._session_auth_context(session_id)
        if not auth_context:
            raise ValueError(
                "operation_not_allowed: Write access is not confirmed for this session. Authenticate successfully before attempting writes."
            )
        if self._coerce_bool(auth_context.get("ro")):
            raise ValueError(
                "space_read_only: This agent has read-only access and cannot upload files in this Safe."
            )

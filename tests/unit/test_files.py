from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from unolock_mcp.api.files import UnoLockReadonlyFilesClient, UnoLockWritableFilesClient
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.crypto.safe_keyring import SafeKeyringManager


class UnoLockFilesClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_store = SessionStore()
        self.session_store._auth_contexts["session-1"] = {"ro": False}
        self.keyring = SafeKeyringManager()
        self.keyring.init_with_safe_access_master_key(b"1" * 32)
        self.agent_auth = Mock()
        self.agent_auth.get_keyring_for_session.return_value = self.keyring
        self.api_client = Mock()
        self.api_client.http_client = Mock()
        self.readonly_client = UnoLockReadonlyFilesClient(self.api_client, self.agent_auth, self.session_store)
        self.writable_client = UnoLockWritableFilesClient(self.api_client, self.agent_auth, self.session_store)

    def _encrypted_metadata(self, metadata: dict[str, object], sid: int) -> str:
        return self.keyring.encrypt_string(json.dumps(metadata, separators=(",", ":")), sid=sid)

    def test_list_files_only_returns_cloud_archives(self) -> None:
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [
                    {
                        "id": "cloud-1",
                        "t": "Cloud",
                        "sid": 42,
                        "m": self._encrypted_metadata(
                            {"name": "report.pdf", "type": "application/pdf", "spaceName": "Main"},
                            42,
                        ),
                        "fs": 1234,
                        "s": 1600,
                        "p": [1600],
                    },
                    {
                        "id": "local-1",
                        "t": "Local",
                        "sid": 42,
                        "m": self._encrypted_metadata({"name": "local.ulf"}, 42),
                    },
                    {
                        "id": "msg-1",
                        "t": "Msg",
                        "sid": 42,
                        "m": self._encrypted_metadata({"name": "message.bin"}, 42),
                    },
                ],
            }
        }

        result = self.readonly_client.list_files("session-1")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["files"][0]["archive_id"], "cloud-1")
        self.assertEqual(result["files"][0]["name"], "report.pdf")
        self.assertEqual(
            result["files"][0]["allowed_operations"],
            ["get_file", "download_file", "rename_file", "replace_file", "delete_file"],
        )

    def test_download_file_reassembles_and_decrypts_parts(self) -> None:
        archive_id = "cloud-1"
        chunk_one = b"hello "
        chunk_two = b"world"
        encrypted_one, kek = self.keyring.encrypt_bytes_with_kek(
            chunk_one,
            archive_id=archive_id,
            sid=42,
            kek=None,
        )
        encrypted_two, kek = self.keyring.encrypt_bytes_with_kek(
            chunk_two,
            archive_id=archive_id,
            sid=42,
            kek=kek,
        )
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [
                    {
                        "id": archive_id,
                        "t": "Cloud",
                        "sid": 42,
                        "m": self._encrypted_metadata(
                            {
                                "name": "greeting.txt",
                                "type": "text/plain",
                                "spaceName": "Main",
                                "kek": kek,
                            },
                            42,
                        ),
                        "fs": len(chunk_one) + len(chunk_two),
                        "s": len(encrypted_one) + len(encrypted_two),
                        "p": [len(encrypted_one), len(encrypted_two)],
                    }
                ],
            }
        }
        self.api_client.get_download_url.return_value = {
            "callback": {"type": "GetDownloadUrl", "result": "https://download.example/file"}
        }

        def _download_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
            if not headers:
                return encrypted_one + encrypted_two
            range_header = headers.get("Range")
            if range_header == f"bytes=0-{len(encrypted_one) - 1}":
                return encrypted_one
            if range_header == f"bytes={len(encrypted_one)}-{len(encrypted_one) + len(encrypted_two) - 1}":
                return encrypted_two
            raise AssertionError(f"Unexpected range header: {range_header}")

        self.api_client.http_client.get_bytes_absolute.side_effect = _download_bytes

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "greeting.txt"
            result = self.readonly_client.download_file(
                "session-1",
                archive_id=archive_id,
                output_path=str(output_path),
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.read_bytes(), chunk_one + chunk_two)
            self.assertEqual(result["bytes_written"], len(chunk_one) + len(chunk_two))

    def test_download_file_rejects_existing_path_without_overwrite(self) -> None:
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [
                    {
                        "id": "cloud-1",
                        "t": "Cloud",
                        "sid": 42,
                        "m": self._encrypted_metadata({"name": "report.txt", "type": "text/plain"}, 42),
                        "fs": 5,
                        "s": 16,
                        "p": [16],
                    }
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.txt"
            output_path.write_text("existing", encoding="utf8")

            with self.assertRaisesRegex(ValueError, "output_path already exists"):
                self.readonly_client.download_file(
                    "session-1",
                    archive_id="cloud-1",
                    output_path=str(output_path),
                )

    def test_get_file_rejects_non_cloud_archive(self) -> None:
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [
                    {
                        "id": "msg-1",
                        "t": "Msg",
                        "sid": 42,
                        "m": self._encrypted_metadata({"name": "message.bin"}, 42),
                    }
                ],
            }
        }

        with self.assertRaisesRegex(ValueError, "Only Cloud files are supported"):
            self.readonly_client.get_file("session-1", "msg-1")

    def test_upload_file_rejects_read_only_session(self) -> None:
        self.session_store._auth_contexts["session-1"] = {"ro": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "payload.bin"
            source_path.write_bytes(b"abc")

            with self.assertRaisesRegex(ValueError, "read-only access"):
                self.writable_client.upload_file(
                    "session-1",
                    space_id=42,
                    local_path=str(source_path),
                )

    def test_upload_file_creates_cloud_archive_and_completes_multipart_upload(self) -> None:
        archive_id = "cloud-1"
        records_archive = {
            "id": "records-1",
            "t": "Records",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata({"tr": "lput", "spaceName": "Main"}, 42),
        }

        file_bytes = b"abcdefgh"
        with patch.object(UnoLockWritableFilesClient, "CHUNK_SIZE", 4):
            first_chunk = file_bytes[:4]
            second_chunk = file_bytes[4:]
            encrypted_one, kek = self.keyring.encrypt_bytes_with_kek(
                first_chunk,
                archive_id=archive_id,
                sid=42,
                kek=None,
            )
            encrypted_two, kek = self.keyring.encrypt_bytes_with_kek(
                second_chunk,
                archive_id=archive_id,
                sid=42,
                kek=kek,
            )
            cloud_archive = {
                "id": archive_id,
                "t": "Cloud",
                "sid": 42,
                "l": "17",
                "m": self._encrypted_metadata(
                    {
                        "name": "payload.bin",
                        "type": "application/octet-stream",
                        "spaceName": "Main",
                        "kek": kek,
                    },
                    42,
                ),
                "fs": len(file_bytes),
                "s": len(encrypted_one) + len(encrypted_two),
                "p": [len(encrypted_one), len(encrypted_two)],
            }

            self.api_client.get_spaces.return_value = {
                "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
            }
            self.api_client.get_archives.side_effect = [
                {"callback": {"type": "GetArchives", "result": [records_archive]}},
                {"callback": {"type": "GetArchives", "result": [records_archive, cloud_archive]}},
            ]
            self.api_client.create_archive.return_value = {
                "callback": {"type": "CreateArchive", "result": {"id": archive_id, "t": "Cloud", "sid": 42, "l": "17"}}
            }
            self.api_client.init_archive_upload.return_value = {
                "callback": {
                    "type": "InitArchiveUpload",
                    "result": {"uploadId": "upload-1", "signedUrl": "https://upload.example/part-1"},
                }
            }
            self.api_client.get_archive_upload_url.return_value = {
                "callback": {"type": "GetArchiveUploadUrl", "result": "https://upload.example/part-2"}
            }
            self.api_client.complete_archive_upload.return_value = {
                "callback": {"type": "CompleteArchiveUpload", "result": {"result": "SUCCESS", "safeExp": 123}}
            }
            self.api_client.http_client.put_bytes_absolute.side_effect = [
                {"status": 200, "headers": {"ETag": '"etag-1"'}, "body": b""},
                {"status": 200, "headers": {"ETag": '"etag-2"'}, "body": b""},
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = Path(tmpdir) / "payload.bin"
                source_path.write_bytes(file_bytes)

                result = self.writable_client.upload_file(
                    "session-1",
                    space_id=42,
                    local_path=str(source_path),
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["file"]["archive_id"], archive_id)
        self.assertEqual(self.api_client.http_client.put_bytes_absolute.call_count, 2)
        complete_kwargs = self.api_client.complete_archive_upload.call_args.kwargs
        self.assertEqual(complete_kwargs["archive_id"], archive_id)
        self.assertEqual(complete_kwargs["upload_id"], "upload-1")
        self.assertIsInstance(complete_kwargs["metadata"], str)
        self.assertEqual(len(complete_kwargs["parts"]), 2)
        self.api_client.delete_archive.assert_not_called()

    def test_upload_file_deletes_created_archive_after_part_upload_failure(self) -> None:
        archive_id = "cloud-1"
        records_archive = {
            "id": "records-1",
            "t": "Records",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata({"tr": "lput", "spaceName": "Main"}, 42),
        }
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {"type": "GetArchives", "result": [records_archive]}
        }
        self.api_client.create_archive.return_value = {
            "callback": {"type": "CreateArchive", "result": {"id": archive_id, "t": "Cloud", "sid": 42, "l": "17"}}
        }
        self.api_client.init_archive_upload.return_value = {
            "callback": {
                "type": "InitArchiveUpload",
                "result": {"uploadId": "upload-1", "signedUrl": "https://upload.example/part-1"},
            }
        }
        self.api_client.http_client.put_bytes_absolute.side_effect = RuntimeError("network broke")
        self.api_client.abort_multipart_upload.return_value = {
            "callback": {"type": "AbortMultipartUpload", "result": {}}
        }
        self.api_client.delete_archive.return_value = {
            "callback": {"type": "DeleteArchive", "result": {}}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "payload.bin"
            source_path.write_bytes(b"abcdefgh")

            with self.assertRaisesRegex(RuntimeError, "network broke"):
                self.writable_client.upload_file(
                    "session-1",
                    space_id=42,
                    local_path=str(source_path),
                )

        self.api_client.abort_multipart_upload.assert_called_once()
        self.api_client.delete_archive.assert_called_once_with("session-1", archive_id)

    def test_rename_file_updates_cloud_metadata(self) -> None:
        archive_id = "cloud-1"
        updated_archive = {
            "id": archive_id,
            "t": "Cloud",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata({"name": "renamed.txt", "type": "text/plain"}, 42),
            "fs": 5,
            "s": 16,
            "p": [16],
        }
        self.api_client.get_spaces.side_effect = [
            {"callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}}
        ]
        self.api_client.get_archives.side_effect = [
            {
                "callback": {
                    "type": "GetArchives",
                    "result": [
                        {
                            "id": archive_id,
                            "t": "Cloud",
                            "sid": 42,
                            "l": "17",
                            "m": self._encrypted_metadata({"name": "old.txt", "type": "text/plain"}, 42),
                            "fs": 5,
                            "s": 16,
                            "p": [16],
                        }
                    ],
                }
            },
            {"callback": {"type": "GetArchives", "result": [updated_archive]}},
        ]
        self.api_client.update_archive.return_value = {
            "callback": {"type": "UpdateArchive", "result": {"id": archive_id}}
        }

        result = self.writable_client.rename_file("session-1", archive_id=archive_id, name="renamed.txt")

        self.assertTrue(result["ok"])
        self.assertEqual(result["file"]["name"], "renamed.txt")
        update_request = self.api_client.update_archive.call_args.args[1]
        self.assertEqual(update_request["m"]["name"], "renamed.txt")

    def test_delete_file_removes_cloud_archive(self) -> None:
        archive_id = "cloud-1"
        archive = {
            "id": archive_id,
            "t": "Cloud",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata({"name": "trash.txt", "type": "text/plain"}, 42),
            "fs": 5,
            "s": 16,
            "p": [16],
        }
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {"type": "GetArchives", "result": [archive]}
        }
        self.api_client.delete_archive.return_value = {
            "callback": {"type": "DeleteArchive", "result": {}}
        }

        result = self.writable_client.delete_file("session-1", archive_id=archive_id)

        self.assertTrue(result["ok"])
        self.assertTrue(result["deleted"])
        self.assertEqual(result["file"]["archive_id"], archive_id)
        self.api_client.delete_archive.assert_called_once_with("session-1", archive_id)

    def test_replace_file_reuses_existing_cloud_archive(self) -> None:
        archive_id = "cloud-1"
        _, starting_kek = self.keyring.encrypt_bytes_with_kek(
            b"seed",
            archive_id=archive_id,
            sid=42,
            kek=None,
        )
        existing_archive = {
            "id": archive_id,
            "t": "Cloud",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata(
                {"name": "payload.bin", "type": "application/octet-stream", "spaceName": "Main", "kek": starting_kek},
                42,
            ),
            "fs": 8,
            "s": 20,
            "p": [20],
        }

        file_bytes = b"abcdefgh"
        with patch.object(UnoLockWritableFilesClient, "CHUNK_SIZE", 4):
            encrypted_one, next_kek = self.keyring.encrypt_bytes_with_kek(
                file_bytes[:4],
                archive_id=archive_id,
                sid=42,
                kek=starting_kek,
            )
            encrypted_two, next_kek = self.keyring.encrypt_bytes_with_kek(
                file_bytes[4:],
                archive_id=archive_id,
                sid=42,
                kek=next_kek,
            )
            refreshed_archive = {
                "id": archive_id,
                "t": "Cloud",
                "sid": 42,
                "l": "17",
                "m": self._encrypted_metadata(
                    {
                        "name": "replacement.bin",
                        "type": "application/octet-stream",
                        "spaceName": "Main",
                        "kek": next_kek,
                    },
                    42,
                ),
                "fs": len(file_bytes),
                "s": len(encrypted_one) + len(encrypted_two),
                "p": [len(encrypted_one), len(encrypted_two)],
            }
            self.api_client.get_spaces.return_value = {
                "callback": {"type": "GetSpaces", "result": [{"spaceID": 42, "type": "PRIVATE", "owner": True}]}
            }
            self.api_client.get_archives.side_effect = [
                {"callback": {"type": "GetArchives", "result": [existing_archive]}},
                {"callback": {"type": "GetArchives", "result": [refreshed_archive]}},
            ]
            self.api_client.update_archive.return_value = {
                "callback": {"type": "UpdateArchive", "result": {"id": archive_id}}
            }
            self.api_client.init_archive_upload.return_value = {
                "callback": {
                    "type": "InitArchiveUpload",
                    "result": {"uploadId": "upload-1", "signedUrl": "https://upload.example/part-1"},
                }
            }
            self.api_client.get_archive_upload_url.return_value = {
                "callback": {"type": "GetArchiveUploadUrl", "result": "https://upload.example/part-2"}
            }
            self.api_client.complete_archive_upload.return_value = {
                "callback": {"type": "CompleteArchiveUpload", "result": {"result": "SUCCESS", "safeExp": 123}}
            }
            self.api_client.http_client.put_bytes_absolute.side_effect = [
                {"status": 200, "headers": {"ETag": '"etag-1"'}, "body": b""},
                {"status": 200, "headers": {"ETag": '"etag-2"'}, "body": b""},
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = Path(tmpdir) / "replacement.bin"
                source_path.write_bytes(file_bytes)

                result = self.writable_client.replace_file(
                    "session-1",
                    archive_id=archive_id,
                    local_path=str(source_path),
                    name="replacement.bin",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["file"]["archive_id"], archive_id)
        self.api_client.create_archive.assert_not_called()
        self.api_client.delete_archive.assert_not_called()
        update_request = self.api_client.update_archive.call_args.args[1]
        self.assertEqual(update_request["id"], archive_id)
        self.assertEqual(update_request["fs"], len(file_bytes))
        self.assertEqual(update_request["m"]["name"], "replacement.bin")

    def test_replace_file_failure_aborts_without_deleting_existing_archive(self) -> None:
        archive_id = "cloud-1"
        archive = {
            "id": archive_id,
            "t": "Cloud",
            "sid": 42,
            "l": "17",
            "m": self._encrypted_metadata({"name": "payload.bin", "type": "application/octet-stream"}, 42),
            "fs": 8,
            "s": 20,
            "p": [20],
        }
        self.api_client.get_archives.return_value = {
            "callback": {"type": "GetArchives", "result": [archive]}
        }
        self.api_client.update_archive.return_value = {
            "callback": {"type": "UpdateArchive", "result": {"id": archive_id}}
        }
        self.api_client.init_archive_upload.return_value = {
            "callback": {
                "type": "InitArchiveUpload",
                "result": {"uploadId": "upload-1", "signedUrl": "https://upload.example/part-1"},
            }
        }
        self.api_client.http_client.put_bytes_absolute.side_effect = RuntimeError("network broke")
        self.api_client.abort_multipart_upload.return_value = {
            "callback": {"type": "AbortMultipartUpload", "result": {}}
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "replacement.bin"
            source_path.write_bytes(b"abcdefgh")

            with self.assertRaisesRegex(RuntimeError, "network broke"):
                self.writable_client.replace_file(
                    "session-1",
                    archive_id=archive_id,
                    local_path=str(source_path),
                )

        self.api_client.abort_multipart_upload.assert_called_once()
        self.api_client.delete_archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()

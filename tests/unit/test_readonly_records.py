from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from unolock_mcp.api.records import UnoLockReadonlyRecordsClient, UnoLockWritableRecordsClient
from unolock_mcp.crypto.safe_keyring import SafeKeyringManager


class UnoLockReadonlyRecordsClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = UnoLockReadonlyRecordsClient(api_client=None, agent_auth=None)  # type: ignore[arg-type]

    def test_extracts_plain_text_from_quill_delta(self) -> None:
        plain_text = self.client._extract_text_from_delta(
            '{"ops":[{"insert":"Hello"},{"insert":" world\\n"},{"insert":{"image":"x"}}]}'
        )
        self.assertEqual(plain_text, "Hello world")

    def test_projects_checklist_items_as_plain_text(self) -> None:
        items = self.client._project_checklist_items(
            [
                {"id": 4, "data": "<div>First <strong>item</strong></div>", "done": False},
                {"id": 5, "data": "Second", "done": True},
            ]
        )

        self.assertEqual(
            items,
            [
                {
                    "id": 4,
                    "text": "First item",
                    "done": False,
                    "checked": False,
                    "state": "unchecked",
                    "order": 0,
                },
                {
                    "id": 5,
                    "text": "Second",
                    "done": True,
                    "checked": True,
                    "state": "checked",
                    "order": 1,
                },
            ],
        )

    def test_projects_note_record_with_agent_friendly_fields(self) -> None:
        projected = self.client._project_record(
            {
                "id": 12,
                "version": 7,
                "recordTitle": "Daily plan",
                "recordBody": '{"ops":[{"insert":"One\\nTwo\\n"}]}',
                "pinned": True,
                "isCbox": False,
                "labels": [{"id": 1, "name": "work"}],
                "ro": True,
            },
            {
                "id": "archive-1",
                "sid": 101,
                "m": {"spaceName": "Main"},
            },
            {},
        )

        self.assertEqual(projected["record_ref"], "archive-1:12")
        self.assertEqual(projected["kind"], "note")
        self.assertEqual(projected["version"], 7)
        self.assertEqual(projected["plain_text"], "One\nTwo")
        self.assertEqual(projected["space_name"], "Main")
        self.assertEqual(projected["labels"], [{"id": 1, "name": "work"}])
        self.assertTrue(projected["read_only"])
        self.assertTrue(projected["locked"])

    def test_label_name_filtering_uses_lowercase_names(self) -> None:
        names = self.client._label_names(
            {
                "labels": [
                    {"id": 1, "name": "Work"},
                    {"id": 2, "name": "Personal"},
                    {"id": 3},
                ]
            }
        )
        self.assertEqual(names, {"work", "personal"})


class UnoLockWritableRecordsClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.keyring = SafeKeyringManager()
        self.keyring.init_with_safe_access_master_key(b"1" * 32)
        self.agent_auth = Mock()
        self.agent_auth.get_keyring_for_session.return_value = self.keyring
        self.api_client = Mock()
        self.writer = UnoLockWritableRecordsClient(self.api_client, self.agent_auth)

    def test_create_note_returns_version_and_locked_metadata(self) -> None:
        encrypted_payload = self.keyring.encrypt_string(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}',
            sid=101,
        )
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {"type": "GetArchives", "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}]}
        }
        self.api_client.get_download_url.return_value = {
            "callback": {"type": "GetDownloadUrl", "result": "https://download"}
        }
        self.api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": '"old-etag"'})
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.return_value = {
            "callback": {"type": "GetUploadPutUrl", "result": "https://upload"}
        }
        self.api_client.http_client.put_bytes_absolute.return_value = {
            "status": 200,
            "headers": {},
            "body": b"",
        }

        result = self.writer.create_note("session-1", space_id=101, title="New note", text="hello world")

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 1)
        self.assertFalse(result["record"]["read_only"])
        self.assertFalse(result["record"]["locked"])
        self.assertEqual(result["record"]["plain_text"], "hello world")
        self.assertEqual(result["record"]["title"], "New note")

    def test_create_note_uploads_original_ciphertext_and_only_updates_kek_metadata(self) -> None:
        encrypted_payload = self.keyring.encrypt_string(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}',
            sid=101,
        )
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}],
            }
        }
        self.api_client.get_download_url.return_value = {
            "callback": {"type": "GetDownloadUrl", "result": "https://download"}
        }
        self.api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": '"old-etag"'})
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.return_value = {
            "callback": {"type": "GetUploadPutUrl", "result": "https://upload"}
        }
        self.api_client.http_client.put_bytes_absolute.return_value = {
            "status": 200,
            "headers": {},
            "body": b"",
        }

        self.writer.create_note("session-1", space_id=101, title="New note", text="hello world")

        uploaded_body = self.api_client.http_client.put_bytes_absolute.call_args.args[1]
        updated_archive = self.api_client.update_archive.call_args.args[1]

        self.assertIsInstance(uploaded_body, bytes)
        self.assertNotEqual(updated_archive["m"]["kek"], None)
        payload = json.loads(
            self.keyring.decrypt_string(uploaded_body.decode("utf8"), sid=101)
        )
        self.assertEqual(payload["data"]["nextRecordID"], 1)
        self.assertEqual(len(payload["data"]["records"]), 1)
        self.assertEqual(payload["data"]["records"][0]["recordTitle"], "New note")

    def test_create_checklist_projects_item_state(self) -> None:
        encrypted_payload = self.keyring.encrypt_string(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}',
            sid=101,
        )
        self.api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        self.api_client.get_archives.return_value = {
            "callback": {"type": "GetArchives", "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}]}
        }
        self.api_client.get_download_url.return_value = {
            "callback": {"type": "GetDownloadUrl", "result": "https://download"}
        }
        self.api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": '"old-etag"'})
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.return_value = {
            "callback": {"type": "GetUploadPutUrl", "result": "https://upload"}
        }
        self.api_client.http_client.put_bytes_absolute.return_value = {
            "status": 200,
            "headers": {},
            "body": b"",
        }

        result = self.writer.create_checklist(
            "session-1",
            space_id=101,
            title="Tasks",
            items=["first", "second"],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["kind"], "checklist")
        self.assertEqual(
            result["record"]["checklist_items"],
            [
                {"id": 0, "text": "first", "done": False, "checked": False, "state": "unchecked", "order": 0},
                {"id": 1, "text": "second", "done": False, "checked": False, "state": "unchecked", "order": 1},
            ],
        )


if __name__ == "__main__":
    unittest.main()

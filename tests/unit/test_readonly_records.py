from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from unolock_mcp.api.records import UnoLockReadonlyRecordsClient, UnoLockWritableRecordsClient
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.domain.models import CallbackAction, FlowSession
from unolock_mcp.crypto.safe_keyring import SafeKeyringManager


class UnoLockReadonlyRecordsClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_store = SessionStore()
        self.client = UnoLockReadonlyRecordsClient(
            api_client=None,  # type: ignore[arg-type]
            agent_auth=None,  # type: ignore[arg-type]
            session_store=self.session_store,
        )

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
        self.assertFalse(projected["writable"])
        self.assertEqual(projected["allowed_operations"], ["get_record"])

    def test_string_false_record_ro_does_not_make_record_read_only(self) -> None:
        self.session_store._auth_contexts["session-1"] = {"ro": False}
        projected = self.client._project_record(
            {
                "id": 13,
                "version": 1,
                "recordTitle": "Writable note",
                "recordBody": '{"ops":[{"insert":"Body\\n"}]}',
                "pinned": False,
                "isCbox": False,
                "labels": [],
                "ro": "false",
            },
            {
                "id": "archive-2",
                "sid": 101,
                "m": {"spaceName": "Main"},
            },
            {},
            session_id="session-1",
        )

        self.assertFalse(projected["read_only"])
        self.assertFalse(projected["locked"])
        self.assertTrue(projected["writable"])
        self.assertIn("update_note", projected["allowed_operations"])

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

    def test_get_record_uses_cached_archive_snapshot_when_available(self) -> None:
        keyring = SafeKeyringManager()
        keyring.init_with_safe_access_master_key(b"1" * 32)
        agent_auth = Mock()
        agent_auth.get_keyring_for_session.return_value = keyring
        api_client = Mock()
        client = UnoLockReadonlyRecordsClient(api_client, agent_auth, self.session_store)

        payload = {
            "title": "Records",
            "data": {
                "nextRecordID": 1,
                "nextLabelID": 0,
                "labels": [],
                "records": [
                    {
                        "id": 1,
                        "version": 2,
                        "recordTitle": "Cached note",
                        "recordBody": '{"ops":[{"insert":"cached body\\n"}]}',
                        "pinned": False,
                        "bgColor": "",
                        "bgImage": "",
                        "color": "",
                        "isCbox": False,
                        "labels": [],
                        "archives": None,
                        "wallet": None,
                        "ro": False,
                    }
                ],
            },
        }
        self.session_store.put_records_archive_snapshot(
            "session-1",
            "archive-1",
            {
                "archive": {"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}},
                "body": payload,
                "etag": '"old-etag"',
                "transfer_mode": "lput",
                "space_id": 101,
            },
        )
        api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}],
            }
        }

        record = client.get_record("session-1", "archive-1:1")

        self.assertEqual(record["title"], "Cached note")
        self.assertEqual(record["plain_text"], "cached body")
        api_client.get_download_url.assert_not_called()
        api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_get_record_refreshes_stale_cached_archive_snapshot(self) -> None:
        keyring = SafeKeyringManager()
        keyring.init_with_safe_access_master_key(b"1" * 32)
        agent_auth = Mock()
        agent_auth.get_keyring_for_session.return_value = keyring
        api_client = Mock()
        client = UnoLockReadonlyRecordsClient(api_client, agent_auth, self.session_store)

        stale_payload = {
            "title": "Records",
            "data": {
                "nextRecordID": 1,
                "nextLabelID": 0,
                "labels": [],
                "records": [
                    {
                        "id": 1,
                        "version": 1,
                        "recordTitle": "Old cached note",
                        "recordBody": '{"ops":[{"insert":"old\\n"}]}',
                        "pinned": False,
                        "bgColor": "",
                        "bgImage": "",
                        "color": "",
                        "isCbox": False,
                        "labels": [],
                        "archives": None,
                        "wallet": None,
                        "ro": False,
                    }
                ],
            },
        }
        fresh_payload = {
            "title": "Records",
            "data": {
                "nextRecordID": 1,
                "nextLabelID": 0,
                "labels": [],
                "records": [
                    {
                        "id": 1,
                        "version": 2,
                        "recordTitle": "Fresh note",
                        "recordBody": '{"ops":[{"insert":"fresh\\n"}]}',
                        "pinned": False,
                        "bgColor": "",
                        "bgImage": "",
                        "color": "",
                        "isCbox": False,
                        "labels": [],
                        "archives": None,
                        "wallet": None,
                        "ro": False,
                    }
                ],
            },
        }
        self.session_store.put_records_archive_snapshot(
            "session-1",
            "archive-1",
            {
                "archive": {"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}},
                "body": stale_payload,
                "etag": '"old-etag"',
                "transfer_mode": "lput",
                "space_id": 101,
            },
        )
        encrypted_payload = keyring.encrypt_string(json.dumps(fresh_payload, separators=(",", ":")), sid=101)
        api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}],
            }
        }
        api_client.get_download_url.return_value = {
            "callback": {"type": "GetDownloadUrl", "result": "https://download"}
        }
        api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": '"new-etag"'})

        with patch("unolock_mcp.auth.session_store.time.time", return_value=1000.0):
            self.session_store.put_records_archive_snapshot(
                "session-1",
                "archive-1",
                {
                    "archive": {"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}},
                    "body": stale_payload,
                    "etag": '"old-etag"',
                    "transfer_mode": "lput",
                    "space_id": 101,
                },
            )

        with patch("unolock_mcp.auth.session_store.time.time", return_value=1301.0):
            record = client.get_record("session-1", "archive-1:1")

        self.assertEqual(record["title"], "Fresh note")
        self.assertEqual(record["version"], 2)
        api_client.get_download_url.assert_called_once()
        api_client.http_client.get_text_with_headers_absolute.assert_called_once()

    def test_list_spaces_includes_writable_and_allowed_operations(self) -> None:
        keyring = SafeKeyringManager()
        keyring.init_with_safe_access_master_key(b"1" * 32)
        session_store = SessionStore()
        session_store.put(
            FlowSession(
                session_id="session-1",
                flow="agentAccess",
                state="state",
                shared_secret=b"secret",
                current_callback=CallbackAction(type="SUCCESS", result={"ro": False, "isAdmin": False}),
                authorized=True,
            )
        )
        agent_auth = Mock()
        agent_auth.get_keyring_for_session.return_value = keyring
        api_client = Mock()
        client = UnoLockReadonlyRecordsClient(api_client, agent_auth, session_store)
        payload = {
            "title": "Records",
            "data": {"nextRecordID": 0, "nextLabelID": 0, "labels": [], "records": []},
        }
        encrypted_payload = keyring.encrypt_string(json.dumps(payload, separators=(",", ":")), sid=101)
        api_client.get_spaces.return_value = {
            "callback": {"type": "GetSpaces", "result": [{"spaceID": 101, "type": "PRIVATE", "owner": True}]}
        }
        api_client.get_archives.return_value = {
            "callback": {
                "type": "GetArchives",
                "result": [{"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}}],
            }
        }
        api_client.get_download_url.return_value = {"callback": {"type": "GetDownloadUrl", "result": "https://download"}}
        api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": '"etag"'})

        result = client.list_spaces("session-1")

        self.assertEqual(result["spaces"][0]["writable"], True)
        self.assertIn("create_note", result["spaces"][0]["allowed_operations"])


class UnoLockWritableRecordsClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.keyring = SafeKeyringManager()
        self.keyring.init_with_safe_access_master_key(b"1" * 32)
        self.agent_auth = Mock()
        self.agent_auth.get_keyring_for_session.return_value = self.keyring
        self.api_client = Mock()
        self.session_store = SessionStore()
        self.writer = UnoLockWritableRecordsClient(self.api_client, self.agent_auth, self.session_store)
        self._authorize_session()

    def _authorize_session(self, *, ro: bool = False) -> None:
        self.session_store.put(
            FlowSession(
                session_id="session-1",
                flow="agentAccess",
                state="state",
                shared_secret=b"secret",
                current_callback=CallbackAction(type="SUCCESS", result={"ro": ro, "isAdmin": False}),
                authorized=True,
            )
        )

    def _prime_records_archive(self, payload: str, *, etag: str = '"old-etag"') -> None:
        encrypted_payload = self.keyring.encrypt_string(payload, sid=101)
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
        self.api_client.http_client.get_text_with_headers_absolute.return_value = (encrypted_payload, {"ETag": etag})
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.return_value = {
            "callback": {"type": "GetUploadPutUrl", "result": "https://upload"}
        }
        self.api_client.http_client.put_bytes_absolute.return_value = {
            "status": 200,
            "headers": {},
            "body": b"",
        }

    def _cache_records_archive(self, payload: str, *, etag: str = '"old-etag"') -> None:
        self.session_store.put_records_archive_snapshot(
            "session-1",
            "archive-1",
            {
                "archive": {"id": "archive-1", "t": "Records", "sid": 101, "m": {"tr": "lput", "spaceName": "Main"}},
                "body": json.loads(payload),
                "etag": etag,
                "transfer_mode": "lput",
                "space_id": 101,
            },
        )

    def test_create_note_returns_version_and_locked_metadata(self) -> None:
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

        result = self.writer.create_note("session-1", space_id=101, title="New note", text="hello world")

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 1)
        self.assertFalse(result["record"]["read_only"])
        self.assertFalse(result["record"]["locked"])
        self.assertTrue(result["record"]["writable"])
        self.assertIn("update_note", result["record"]["allowed_operations"])
        self.assertEqual(result["record"]["plain_text"], "hello world")
        self.assertEqual(result["record"]["title"], "New note")

    def test_create_note_rejects_read_only_session_before_upload(self) -> None:
        self._authorize_session(ro=True)
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

        with self.assertRaisesRegex(ValueError, "space_read_only"):
            self.writer.create_note("session-1", space_id=101, title="New note", text="hello world")

        self.api_client.get_upload_put_url.assert_not_called()

    def test_create_note_uploads_original_ciphertext_and_only_updates_kek_metadata(self) -> None:
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

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
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

        result = self.writer.create_checklist(
            "session-1",
            space_id=101,
            title="Tasks",
            items=[{"text": "first"}, {"text": "second"}],
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

    def test_create_checklist_accepts_structured_items_with_initial_state(self) -> None:
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

        result = self.writer.create_checklist(
            "session-1",
            space_id=101,
            title="Tasks",
            items=[
                {"text": "first", "checked": True},
                {"text": "second", "done": False},
                {"text": "third", "state": "checked"},
                {"text": "fourth"},
            ],
        )

        self.assertEqual(
            result["record"]["checklist_items"],
            [
                {"id": 0, "text": "first", "done": True, "checked": True, "state": "checked", "order": 0},
                {"id": 1, "text": "second", "done": False, "checked": False, "state": "unchecked", "order": 1},
                {"id": 2, "text": "third", "done": True, "checked": True, "state": "checked", "order": 2},
                {"id": 3, "text": "fourth", "done": False, "checked": False, "state": "unchecked", "order": 3},
            ],
        )

    def test_create_checklist_rejects_invalid_items(self) -> None:
        self._prime_records_archive(
            '{"title":"Records","data":{"nextRecordID":0,"nextLabelID":0,"labels":[],"records":[]}}'
        )

        with self.assertRaisesRegex(ValueError, "Each checklist item must include a text string"):
            self.writer.create_checklist(
                "session-1",
                space_id=101,
                title="Tasks",
                items=[{"checked": True}],
            )

    def test_update_note_increments_version(self) -> None:
        payload = '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":[{"id":1,"version":3,"recordTitle":"Old","recordBody":"{\\"ops\\":[{\\"insert\\":\\"before\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}]}}'
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        result = self.writer.update_note(
            "session-1",
            record_ref="archive-1:1",
            expected_version=3,
            title="Updated",
            text="after",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 4)
        self.assertEqual(result["record"]["title"], "Updated")
        self.assertEqual(result["record"]["plain_text"], "after")
        self.api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_update_note_rejects_locked_record(self) -> None:
        payload = '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":[{"id":1,"version":2,"recordTitle":"Locked","recordBody":"{\\"ops\\":[{\\"insert\\":\\"before\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":true}]}}'
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "record_locked"):
            self.writer.update_note(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                title="Updated",
                text="after",
            )

    def test_update_note_rejects_stale_version(self) -> None:
        payload = '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":[{"id":1,"version":4,"recordTitle":"Old","recordBody":"{\\"ops\\":[{\\"insert\\":\\"before\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}]}}'
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "conflict_requires_reread"):
            self.writer.update_note(
                "session-1",
                record_ref="archive-1:1",
                expected_version=3,
                title="Updated",
                text="after",
            )

    def test_update_note_retries_after_archive_conflict_when_record_version_is_unchanged(self) -> None:
        plain_payload = '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":[{"id":1,"version":3,"recordTitle":"Old","recordBody":"{\\"ops\\":[{\\"insert\\":\\"before\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}]}}'
        initial_payload = self.keyring.encrypt_string(plain_payload, sid=101)
        retry_payload = self.keyring.encrypt_string(
            plain_payload,
            sid=101,
        )
        self._cache_records_archive(plain_payload)
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
        self.api_client.http_client.get_text_with_headers_absolute.side_effect = [
            (initial_payload, {"ETag": '"old-etag"'}),
            (retry_payload, {"ETag": '"new-etag"'}),
        ]
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.side_effect = [
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-1"}},
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-2"}},
        ]
        self.api_client.http_client.put_bytes_absolute.side_effect = [
            Exception("412 precondition failed"),
            {"status": 200, "headers": {}, "body": b""},
        ]

        result = self.writer.update_note(
            "session-1",
            record_ref="archive-1:1",
            expected_version=3,
            title="Updated",
            text="after",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 4)
        self.assertEqual(self.api_client.http_client.put_bytes_absolute.call_count, 2)
        self.assertEqual(self.api_client.http_client.get_text_with_headers_absolute.call_count, 1)

    def test_update_note_requires_cached_read_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Read the note first"):
            self.writer.update_note(
                "session-1",
                record_ref="archive-1:1",
                expected_version=1,
                title="Updated",
                text="after",
            )

    def test_rename_record_changes_title_only_and_increments_version(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":3,"recordTitle":"Old title","recordBody":"{\\"ops\\":[{\\"insert\\":\\"body\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}'
            ']}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        result = self.writer.rename_record(
            "session-1",
            record_ref="archive-1:1",
            expected_version=3,
            title="New title",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["title"], "New title")
        self.assertEqual(result["record"]["plain_text"], "body")
        self.assertEqual(result["record"]["version"], 4)
        self.api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_rename_record_rejects_locked_record(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Locked","recordBody":"{\\"ops\\":[{\\"insert\\":\\"body\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":true}'
            ']}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "record_locked"):
            self.writer.rename_record(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                title="New title",
            )

    def test_rename_record_rejects_stale_version(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":4,"recordTitle":"Old title","recordBody":"{\\"ops\\":[{\\"insert\\":\\"body\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}'
            ']}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "conflict_requires_reread"):
            self.writer.rename_record(
                "session-1",
                record_ref="archive-1:1",
                expected_version=3,
                title="New title",
            )

    def test_rename_record_requires_cached_read_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Read the record first"):
            self.writer.rename_record(
                "session-1",
                record_ref="archive-1:1",
                expected_version=1,
                title="New title",
            )

    def test_rename_record_retries_after_archive_conflict_when_record_version_is_unchanged(self) -> None:
        plain_payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":3,"recordTitle":"Old title","recordBody":"{\\"ops\\":[{\\"insert\\":\\"body\\\\n\\"}]}","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":false,"labels":[],"archives":null,"wallet":null,"ro":false}'
            ']}}'
        )
        initial_payload = self.keyring.encrypt_string(plain_payload, sid=101)
        self._cache_records_archive(plain_payload)
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
        self.api_client.http_client.get_text_with_headers_absolute.side_effect = [
            (initial_payload, {"ETag": '"new-etag"'}),
        ]
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.side_effect = [
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-1"}},
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-2"}},
        ]
        self.api_client.http_client.put_bytes_absolute.side_effect = [
            Exception("412 precondition failed"),
            {"status": 200, "headers": {}, "body": b""},
        ]

        result = self.writer.rename_record(
            "session-1",
            record_ref="archive-1:1",
            expected_version=3,
            title="New title",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["title"], "New title")
        self.assertEqual(result["record"]["version"], 4)
        self.assertEqual(self.api_client.http_client.put_bytes_absolute.call_count, 2)
        self.assertEqual(self.api_client.http_client.get_text_with_headers_absolute.call_count, 1)

    def test_set_checklist_item_done_increments_version(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false},{"id":1,"data":"second","done":true}]'
            '}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        result = self.writer.set_checklist_item_done(
            "session-1",
            record_ref="archive-1:1",
            expected_version=2,
            item_id=0,
            done=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 3)
        self.assertEqual(result["record"]["checklist_items"][0]["state"], "checked")
        self.assertEqual(result["record"]["checklist_items"][1]["state"], "checked")
        self.api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_set_checklist_item_done_rejects_locked_record(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":true,'
            '"checkBoxes":[{"id":0,"data":"first","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "record_locked"):
            self.writer.set_checklist_item_done(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                item_id=0,
                done=True,
            )

    def test_set_checklist_item_done_rejects_stale_version(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":4,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "conflict_requires_reread"):
            self.writer.set_checklist_item_done(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                item_id=0,
                done=True,
            )

    def test_set_checklist_item_done_requires_cached_read_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Read the checklist first"):
            self.writer.set_checklist_item_done(
                "session-1",
                record_ref="archive-1:1",
                expected_version=1,
                item_id=0,
                done=True,
            )

    def test_set_checklist_item_done_retries_after_archive_conflict_when_record_version_is_unchanged(self) -> None:
        plain_payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false},{"id":1,"data":"second","done":false}]}]}}'
        )
        initial_payload = self.keyring.encrypt_string(plain_payload, sid=101)
        retry_payload = self.keyring.encrypt_string(plain_payload, sid=101)
        self._cache_records_archive(plain_payload)
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
        self.api_client.http_client.get_text_with_headers_absolute.side_effect = [
            (initial_payload, {"ETag": '"new-etag"'}),
        ]
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.side_effect = [
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-1"}},
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-2"}},
        ]
        self.api_client.http_client.put_bytes_absolute.side_effect = [
            Exception("412 precondition failed"),
            {"status": 200, "headers": {}, "body": b""},
        ]

        result = self.writer.set_checklist_item_done(
            "session-1",
            record_ref="archive-1:1",
            expected_version=2,
            item_id=1,
            done=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 3)
        self.assertEqual(result["record"]["checklist_items"][1]["state"], "checked")
        self.assertEqual(self.api_client.http_client.put_bytes_absolute.call_count, 2)
        self.assertEqual(self.api_client.http_client.get_text_with_headers_absolute.call_count, 1)

    def test_add_checklist_item_increments_version_and_uses_first_free_item_id(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false},{"id":2,"data":"third","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        result = self.writer.add_checklist_item(
            "session-1",
            record_ref="archive-1:1",
            expected_version=2,
            text="second",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 3)
        self.assertEqual(
            result["record"]["checklist_items"],
            [
                {"id": 0, "text": "first", "done": False, "checked": False, "state": "unchecked", "order": 0},
                {"id": 2, "text": "third", "done": False, "checked": False, "state": "unchecked", "order": 1},
                {"id": 1, "text": "second", "done": False, "checked": False, "state": "unchecked", "order": 2},
            ],
        )
        self.api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_add_checklist_item_rejects_empty_text(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "Checklist item text must not be empty"):
            self.writer.add_checklist_item(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                text="   ",
            )

    def test_add_checklist_item_requires_cached_read_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Read the checklist first"):
            self.writer.add_checklist_item(
                "session-1",
                record_ref="archive-1:1",
                expected_version=1,
                text="new item",
            )

    def test_add_checklist_item_retries_after_archive_conflict_when_record_version_is_unchanged(self) -> None:
        plain_payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false}]}]}}'
        )
        initial_payload = self.keyring.encrypt_string(plain_payload, sid=101)
        self._cache_records_archive(plain_payload)
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
        self.api_client.http_client.get_text_with_headers_absolute.side_effect = [
            (initial_payload, {"ETag": '"new-etag"'}),
        ]
        self.api_client.update_archive.return_value = {"callback": {"type": "UpdateArchive", "result": {}}}
        self.api_client.get_upload_put_url.side_effect = [
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-1"}},
            {"callback": {"type": "GetUploadPutUrl", "result": "https://upload-2"}},
        ]
        self.api_client.http_client.put_bytes_absolute.side_effect = [
            Exception("409 conflict"),
            {"status": 200, "headers": {}, "body": b""},
        ]

        result = self.writer.add_checklist_item(
            "session-1",
            record_ref="archive-1:1",
            expected_version=2,
            text="second",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 3)
        self.assertEqual(result["record"]["checklist_items"][-1]["text"], "second")
        self.assertEqual(self.api_client.http_client.put_bytes_absolute.call_count, 2)
        self.assertEqual(self.api_client.http_client.get_text_with_headers_absolute.call_count, 1)

    def test_remove_checklist_item_increments_version(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false},{"id":1,"data":"second","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        result = self.writer.remove_checklist_item(
            "session-1",
            record_ref="archive-1:1",
            expected_version=2,
            item_id=0,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["version"], 3)
        self.assertEqual(
            result["record"]["checklist_items"],
            [
                {"id": 1, "text": "second", "done": False, "checked": False, "state": "unchecked", "order": 0},
            ],
        )
        self.api_client.http_client.get_text_with_headers_absolute.assert_not_called()

    def test_remove_checklist_item_rejects_missing_item(self) -> None:
        payload = (
            '{"title":"Records","data":{"nextRecordID":1,"nextLabelID":0,"labels":[],"records":['
            '{"id":1,"version":2,"recordTitle":"Tasks","recordBody":"","pinned":false,"bgColor":"","bgImage":"","color":"","isCbox":true,"labels":[],"archives":null,"wallet":null,"ro":false,'
            '"checkBoxes":[{"id":0,"data":"first","done":false}]}]}}'
        )
        self._prime_records_archive(payload)
        self._cache_records_archive(payload)

        with self.assertRaisesRegex(ValueError, "Checklist item not found"):
            self.writer.remove_checklist_item(
                "session-1",
                record_ref="archive-1:1",
                expected_version=2,
                item_id=7,
            )

    def test_remove_checklist_item_requires_cached_read_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Read the checklist first"):
            self.writer.remove_checklist_item(
                "session-1",
                record_ref="archive-1:1",
                expected_version=1,
                item_id=0,
            )


if __name__ == "__main__":
    unittest.main()

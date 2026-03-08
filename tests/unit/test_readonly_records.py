from __future__ import annotations

import unittest

from unolock_mcp.api.records import UnoLockReadonlyRecordsClient


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
                {"id": 4, "text": "First item", "done": False, "order": 0},
                {"id": 5, "text": "Second", "done": True, "order": 1},
            ],
        )

    def test_projects_note_record_with_agent_friendly_fields(self) -> None:
        projected = self.client._project_record(
            {
                "id": 12,
                "recordTitle": "Daily plan",
                "recordBody": '{"ops":[{"insert":"One\\nTwo\\n"}]}',
                "pinned": True,
                "isCbox": False,
                "labels": [{"id": 1, "name": "work"}],
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
        self.assertEqual(projected["plain_text"], "One\nTwo")
        self.assertEqual(projected["space_name"], "Main")
        self.assertEqual(projected["labels"], [{"id": 1, "name": "work"}])

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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest

from unolock_mcp.sync.events import SyncEvent


class SyncEventTest(unittest.TestCase):
    def test_event_serializes_as_one_json_line(self) -> None:
        event = SyncEvent(
            level="error",
            event="upload_failed",
            message="Write access is no longer available for this Space.",
            space_id=1773,
            sync_id="syn_01",
            reason="space_read_only",
        )

        line = event.to_json_line()
        payload = json.loads(line)

        self.assertEqual(payload["level"], "error")
        self.assertEqual(payload["event"], "upload_failed")
        self.assertEqual(payload["sync_id"], "syn_01")
        self.assertEqual(payload["reason"], "space_read_only")
        self.assertIn("ts", payload)

    def test_event_rejects_invalid_level(self) -> None:
        with self.assertRaisesRegex(ValueError, "level must be one of"):
            SyncEvent(level="fatal", event="upload_failed", message="boom")

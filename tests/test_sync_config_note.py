from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unolock_mcp.sync.config_note import (
    DEFAULT_SYNC_DEBOUNCE_SECONDS,
    DEFAULT_SYNC_POLL_SECONDS,
    SyncJobConfig,
    SyncManifest,
    is_reserved_sync_config_note_title,
    is_reserved_sync_events_note_title,
    reserved_sync_config_note_title,
    reserved_sync_events_note_title,
)
from unolock_mcp.sync.reconciler import reconcile_manifests
from unolock_mcp.sync.runtime_store import SyncRuntimeJob, SyncRuntimeState, SyncRuntimeStore


class SyncConfigNoteTest(unittest.TestCase):
    def test_reserved_note_titles_are_space_scoped(self) -> None:
        self.assertEqual(
            reserved_sync_config_note_title("agent-key"),
            "@unolock-agent.sync-config",
        )
        self.assertEqual(
            reserved_sync_events_note_title("agent-key"),
            "@unolock-agent.sync-events",
        )
        self.assertTrue(is_reserved_sync_config_note_title("@unolock-agent.sync-config"))
        self.assertTrue(is_reserved_sync_config_note_title("@unolock-agent.sync-config:agent-key"))
        self.assertTrue(is_reserved_sync_events_note_title("@unolock-agent.sync-events"))
        self.assertTrue(is_reserved_sync_events_note_title("@unolock-agent.sync-events:agent-key"))

    def test_manifest_round_trips_with_default_push_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = str(Path(tmpdir) / "notes.txt")
            manifest = SyncManifest(
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=local_path,
                        name="notes.txt",
                    ),
                ),
            )

            loaded = SyncManifest.from_note_text(manifest.to_note_text())

        self.assertIsNone(loaded.key_id)
        self.assertEqual(len(loaded.jobs), 1)
        self.assertEqual(loaded.jobs[0].mode, "push")
        self.assertTrue(Path(loaded.jobs[0].local_path).is_absolute())

    def test_manifest_parses_legacy_keyed_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = str(Path(tmpdir) / "notes.txt")
            manifest = SyncManifest.from_note_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "key_id": "agent-key",
                        "jobs": [
                            {
                                "sync_id": "syn_01",
                                "space_id": 1773,
                                "local_path": local_path,
                                "name": "notes.txt",
                            }
                        ],
                    }
                )
            )

        self.assertEqual(manifest.key_id, "agent-key")
        self.assertEqual(manifest.jobs[0].sync_id, "syn_01")

    def test_manifest_rejects_duplicate_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = str(Path(tmpdir) / "same.txt")
            with self.assertRaisesRegex(ValueError, "Duplicate local_path"):
                SyncManifest(
                    jobs=(
                        SyncJobConfig(sync_id="syn_01", space_id=100, local_path=local_path, name="same.txt"),
                        SyncJobConfig(sync_id="syn_02", space_id=100, local_path=local_path, name="same.txt"),
                    ),
                )

    def test_manifest_rejects_invalid_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid sync note JSON"):
            SyncManifest.from_note_text("{bad json")

    def test_reconcile_preserves_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = str(Path(tmpdir) / "notes.txt")
            manifest = SyncManifest(
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=local_path,
                        name="renamed.txt",
                        archive_id="archive-1",
                    ),
                ),
            )
            runtime = SyncRuntimeState(
                jobs=(
                    SyncRuntimeJob(
                        sync_id="syn_01",
                        space_id=1773,
                        archive_id="archive-old",
                        local_path=local_path,
                        local_path_resolved=local_path,
                        name="old.txt",
                        mime_type="text/plain",
                        mode="push",
                        enabled=True,
                        poll_seconds=DEFAULT_SYNC_POLL_SECONDS,
                        debounce_seconds=DEFAULT_SYNC_DEBOUNCE_SECONDS,
                        last_uploaded_sha256="abc123",
                        status="synced",
                    ),
                ),
            )

            reconciled = reconcile_manifests([manifest], runtime)

        self.assertEqual(len(reconciled.jobs), 1)
        self.assertEqual(reconciled.jobs[0].archive_id, "archive-1")
        self.assertEqual(reconciled.jobs[0].name, "renamed.txt")
        self.assertEqual(reconciled.jobs[0].last_uploaded_sha256, "abc123")
        self.assertEqual(reconciled.jobs[0].status, "synced")

    def test_reconcile_rejects_cross_space_local_path_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = str(Path(tmpdir) / "same.txt")
            manifest_a = SyncManifest(
                jobs=(SyncJobConfig(sync_id="syn_01", space_id=100, local_path=local_path, name="same.txt"),),
            )
            manifest_b = SyncManifest(
                jobs=(SyncJobConfig(sync_id="syn_02", space_id=200, local_path=local_path, name="same.txt"),),
            )

            with self.assertRaisesRegex(ValueError, "Local path is configured by multiple sync jobs"):
                reconcile_manifests([manifest_a, manifest_b])

    def test_runtime_store_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "syncs.json"
            store = SyncRuntimeStore(path)
            state = SyncRuntimeState(
                jobs=(
                    SyncRuntimeJob(
                        sync_id="syn_01",
                        space_id=1773,
                        archive_id="archive-1",
                        local_path=str(Path(tmpdir) / "notes.txt"),
                        local_path_resolved=str(Path(tmpdir) / "notes.txt"),
                        name="notes.txt",
                        mime_type="text/plain",
                        mode="push",
                        enabled=True,
                        poll_seconds=DEFAULT_SYNC_POLL_SECONDS,
                        debounce_seconds=DEFAULT_SYNC_DEBOUNCE_SECONDS,
                        last_uploaded_sha256="abc123",
                        last_remote_revision="rev-1",
                        status="synced",
                    ),
                ),
            )

            store.save(state)
            loaded = store.load()

            persisted = json.loads(path.read_text(encoding="utf8"))

        self.assertEqual(len(loaded.jobs), 1)
        self.assertEqual(loaded.jobs[0].last_remote_revision, "rev-1")
        self.assertEqual(loaded.jobs[0].last_uploaded_sha256, "abc123")
        self.assertEqual(persisted["jobs"][0]["status"], "synced")
        if hasattr(path, "exists"):
            self.assertTrue("version" in persisted)

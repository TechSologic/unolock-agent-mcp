from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from unolock_mcp.sync.config_note import (
    DEFAULT_SYNC_DEBOUNCE_SECONDS,
    DEFAULT_SYNC_POLL_SECONDS,
    SyncJobConfig,
    SyncManifest,
    reserved_sync_config_note_title,
)
from unolock_mcp.sync.reconciler import reconcile_manifests
from unolock_mcp.sync.runtime_store import SyncRuntimeStore
from unolock_mcp.sync.service import SyncService


class SyncServiceTest(unittest.TestCase):
    def test_add_sync_creates_reserved_note_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello", encoding="utf8")

            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {
                "spaces": [
                    {
                        "space_id": 1773,
                        "writable": True,
                    }
                ]
            }
            readonly_records.list_records.return_value = {"records": []}
            writable_records = Mock()
            writable_records.create_note.return_value = {"record": {"record_ref": "archive-1:9"}}

            service = SyncService(readonly_records, writable_records, Mock(), Mock(), runtime_store)
            service._generate_sync_id = Mock(return_value="syn_fixed")  # type: ignore[method-assign]

            result = service.add_sync(
                "session-1",
                key_id="agent-key",
                space_id=1773,
                local_path=str(local_path),
            )

            self.assertEqual(result["sync"]["sync_id"], "syn_fixed")
            self.assertEqual(result["sync"]["space_id"], 1773)
            self.assertEqual(result["sync"]["name"], "notes.txt")
            writable_records.create_note.assert_called_once()
            note_call = writable_records.create_note.call_args.kwargs
            self.assertEqual(note_call["space_id"], 1773)
            self.assertEqual(note_call["title"], reserved_sync_config_note_title("agent-key"))
            manifest = json.loads(note_call["text"])
            self.assertEqual(manifest["jobs"][0]["sync_id"], "syn_fixed")
            self.assertEqual(runtime_store.load().jobs[0].sync_id, "syn_fixed")

    def test_list_syncs_reconciles_remote_manifest_into_runtime_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(Path(tmpdir) / "notes.txt"),
                        name="notes.txt",
                        archive_id="archive-1",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {
                "spaces": [
                    {
                        "space_id": 1773,
                        "writable": True,
                    }
                ]
            }
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-1:3",
                        "version": 2,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)

            payload = service.list_syncs("session-1", key_id="agent-key")

            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["syncs"][0]["sync_id"], "syn_01")
            self.assertEqual(runtime_store.load().jobs[0].archive_id, "archive-1")

    def test_list_syncs_uses_new_default_poll_and_debounce_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(Path(tmpdir) / "notes.txt"),
                        name="notes.txt",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-1:3",
                        "version": 2,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)

            payload = service.list_syncs("session-1", key_id="agent-key")

            self.assertEqual(payload["syncs"][0]["poll_seconds"], DEFAULT_SYNC_POLL_SECONDS)
            self.assertEqual(payload["syncs"][0]["debounce_seconds"], DEFAULT_SYNC_DEBOUNCE_SECONDS)

    def test_add_sync_requires_writable_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello", encoding="utf8")
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {
                "spaces": [
                    {
                        "space_id": 1773,
                        "writable": False,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)

            with self.assertRaisesRegex(ValueError, "space_read_only"):
                service.add_sync(
                    "session-1",
                    key_id="agent-key",
                    space_id=1773,
                    local_path=str(local_path),
                )

    def test_add_sync_reports_invalid_sync_config_note_for_malformed_reserved_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello", encoding="utf8")
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {
                "spaces": [
                    {
                        "space_id": 1773,
                        "writable": True,
                    }
                ]
            }
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": '{"key_id":"agent-key","jobs":[]}\n{"oops":true}',
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)

            with self.assertRaisesRegex(ValueError, "invalid_sync_config_note"):
                service.add_sync(
                    "session-1",
                    key_id="agent-key",
                    space_id=1773,
                    local_path=str(local_path),
                )

    def test_sync_status_reports_invalid_sync_config_note_for_malformed_reserved_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {
                "spaces": [
                    {
                        "space_id": 1773,
                        "writable": True,
                    }
                ]
            }
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": '{"key_id":"agent-key","jobs":[]}\n{"oops":true}',
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)

            with self.assertRaisesRegex(ValueError, "invalid_sync_config_note"):
                service.sync_status("session-1", key_id="agent-key")

    def test_run_syncs_uploads_new_file_and_updates_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            writable_files = Mock()
            writable_files.upload_file.return_value = {
                "file": {
                    "archive_id": "archive-1",
                }
            }
            service = SyncService(readonly_records, Mock(), Mock(), writable_files, runtime_store)

            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["status"], "synced")
            writable_files.upload_file.assert_called_once()
            state = runtime_store.load()
            self.assertEqual(state.jobs[0].archive_id, "archive-1")
            self.assertEqual(state.jobs[0].status, "synced")
            self.assertIsNotNone(state.jobs[0].last_uploaded_sha256)

    def test_run_syncs_noops_when_digest_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        archive_id="archive-1",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            first_writable_files = Mock()
            first_writable_files.upload_file.return_value = {
                "file": {
                    "archive_id": "archive-1",
                }
            }
            service = SyncService(readonly_records, Mock(), Mock(), first_writable_files, runtime_store)
            service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)
            writable_files = Mock()
            service = SyncService(readonly_records, Mock(), Mock(), writable_files, runtime_store)

            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertEqual(result["results"][0]["changed"], False)
            writable_files.upload_file.assert_not_called()
            writable_files.replace_file.assert_not_called()

    def test_run_syncs_skips_background_poll_until_interval_elapses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        archive_id="archive-1",
                        poll_seconds=60,
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            service = SyncService(readonly_records, Mock(), Mock(), Mock(), runtime_store)
            service.list_syncs("session-1", key_id="agent-key")
            state = runtime_store.load()
            runtime_store.save(
                type(state)(
                    version=state.version,
                    defaults=state.defaults,
                    jobs=(
                        type(state.jobs[0]).from_json(
                            {
                                **state.jobs[0].to_json(),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                                "status": "synced",
                            }
                        ),
                    ),
                )
            )

            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False, force=False)

            self.assertTrue(result["results"][0]["skipped"])
            self.assertEqual(result["results"][0]["reason"], "poll_interval_not_elapsed")

    def test_run_syncs_forced_manual_run_ignores_poll_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        archive_id="archive-1",
                        poll_seconds=60,
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            writable_files = Mock()
            service = SyncService(readonly_records, Mock(), Mock(), writable_files, runtime_store)
            service.list_syncs("session-1", key_id="agent-key")
            state = runtime_store.load()
            runtime_store.save(
                type(state)(
                    version=state.version,
                    defaults=state.defaults,
                    jobs=(
                        type(state.jobs[0]).from_json(
                            {
                                **state.jobs[0].to_json(),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                                "status": "synced",
                            }
                        ),
                    ),
                )
            )

            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertFalse(result["results"][0].get("skipped", False))

    def test_reconcile_preserves_runtime_archive_binding_when_manifest_omits_archive_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                    ),
                ),
            )
            runtime = reconcile_manifests([manifest], runtime_store.load())
            runtime = runtime_store.save(runtime)
            bound_runtime = runtime_store.save(
                type(runtime)(
                    version=runtime.version,
                    defaults=runtime.defaults,
                    jobs=(
                        type(runtime.jobs[0]).from_json(
                            {
                                **runtime.jobs[0].to_json(),
                                "archive_id": "archive-1",
                            }
                        ),
                    ),
                )
            )

            reconciled = reconcile_manifests([manifest], bound_runtime)

            self.assertEqual(reconciled.jobs[0].archive_id, "archive-1")

    def test_run_syncs_persists_new_archive_binding_into_reserved_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            manifest_payload = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            readonly_records.list_records.side_effect = [
                manifest_payload,
                manifest_payload,
                manifest_payload,
            ]
            writable_records = Mock()
            writable_files = Mock()
            writable_files.upload_file.return_value = {
                "file": {
                    "archive_id": "archive-1",
                }
            }
            service = SyncService(readonly_records, writable_records, Mock(), writable_files, runtime_store)

            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertEqual(result["results"][0]["archive_id"], "archive-1")
            writable_records.update_note.assert_called_once()
            updated_manifest = json.loads(writable_records.update_note.call_args.kwargs["text"])
            self.assertEqual(updated_manifest["jobs"][0]["archive_id"], "archive-1")

    def test_run_syncs_logs_error_events_note_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.side_effect = [
                {
                    "records": [
                        {
                            "title": reserved_sync_config_note_title("agent-key"),
                            "plain_text": manifest.to_note_text(),
                            "record_ref": "archive-notes:1",
                            "version": 1,
                        }
                    ]
                },
                {"records": []},
            ]
            writable_records = Mock()
            writable_records.create_note.return_value = {"record": {"record_ref": "archive-events:1"}}
            writable_files = Mock()
            writable_files.upload_file.side_effect = ValueError("space_read_only: denied")

            service = SyncService(readonly_records, writable_records, Mock(), writable_files, runtime_store)
            result = service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertEqual(result["results"][0]["status"], "blocked")
            writable_records.create_note.assert_called_once()
            self.assertIn("@unolock-agent.sync-events:agent-key", writable_records.create_note.call_args.kwargs["title"])

    def test_run_syncs_dedupes_repeated_error_events_within_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            local_path.write_text("hello world", encoding="utf8")
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.side_effect = [
                {
                    "records": [
                        {
                            "title": reserved_sync_config_note_title("agent-key"),
                            "plain_text": manifest.to_note_text(),
                            "record_ref": "archive-notes:1",
                            "version": 1,
                        }
                    ]
                },
                {"records": []},
                {
                    "records": [
                        {
                            "title": reserved_sync_config_note_title("agent-key"),
                            "plain_text": manifest.to_note_text(),
                            "record_ref": "archive-notes:1",
                            "version": 1,
                        }
                    ]
                },
            ]
            writable_records = Mock()
            writable_records.create_note.return_value = {"record": {"record_ref": "archive-events:1"}}
            writable_files = Mock()
            writable_files.upload_file.side_effect = ValueError("space_read_only: denied")

            service = SyncService(readonly_records, writable_records, Mock(), writable_files, runtime_store)
            service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)
            service.run_syncs("session-1", key_id="agent-key", sync_id="syn_01", run_all=False)

            self.assertEqual(writable_records.create_note.call_count, 1)
            self.assertEqual(writable_records.append_note.call_count, 0)

    def test_remove_sync_updates_manifest_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(sync_id="syn_01", space_id=1773, local_path=str(local_path), name="notes.txt"),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 2,
                    }
                ]
            }
            writable_records = Mock()
            service = SyncService(readonly_records, writable_records, Mock(), Mock(), runtime_store)
            service.list_syncs("session-1", key_id="agent-key")

            result = service.remove_sync("session-1", key_id="agent-key", sync_id="syn_01")

            self.assertTrue(result["removed"])
            writable_records.update_note.assert_called_once()
            self.assertEqual(runtime_store.load().jobs, ())

    def test_remove_sync_accepts_local_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(sync_id="syn_01", space_id=1773, local_path=str(local_path), name="notes.txt"),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 2,
                    }
                ]
            }
            writable_records = Mock()
            service = SyncService(readonly_records, writable_records, Mock(), Mock(), runtime_store)
            service.list_syncs("session-1", key_id="agent-key")

            result = service.remove_sync("session-1", key_id="agent-key", sync_id=str(local_path))

            self.assertTrue(result["removed"])
            self.assertEqual(result["sync"]["sync_id"], "syn_01")
            self.assertEqual(runtime_store.load().jobs, ())

    def test_disable_sync_updates_manifest_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(sync_id="syn_01", space_id=1773, local_path=str(local_path), name="notes.txt"),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 2,
                    }
                ]
            }
            writable_records = Mock()
            service = SyncService(readonly_records, writable_records, Mock(), Mock(), runtime_store)
            service.list_syncs("session-1", key_id="agent-key")

            result = service.disable_sync("session-1", key_id="agent-key", sync_id="syn_01")

            self.assertFalse(result["enabled"])
            writable_records.update_note.assert_called_once()
            manifest_payload = json.loads(writable_records.update_note.call_args.kwargs["text"])
            self.assertFalse(manifest_payload["jobs"][0]["enabled"])
            state = runtime_store.load()
            self.assertFalse(state.jobs[0].enabled)
            self.assertEqual(state.jobs[0].status, "disabled")

    def test_enable_sync_reenables_disabled_job_and_sets_pending_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        enabled=False,
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 2,
                    }
                ]
            }
            writable_records = Mock()
            service = SyncService(readonly_records, writable_records, Mock(), Mock(), runtime_store)
            service.list_syncs("session-1", key_id="agent-key")

            result = service.enable_sync("session-1", key_id="agent-key", sync_id="syn_01")

            self.assertTrue(result["enabled"])
            writable_records.update_note.assert_called_once()
            manifest_payload = json.loads(writable_records.update_note.call_args.kwargs["text"])
            self.assertTrue(manifest_payload["jobs"][0]["enabled"])
            state = runtime_store.load()
            self.assertTrue(state.jobs[0].enabled)
            self.assertEqual(state.jobs[0].status, "new")

    def test_restore_sync_downloads_to_watched_path_and_updates_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        archive_id="archive-1",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            readonly_files = Mock()

            def fake_download_file(_session_id, *, archive_id, output_path, overwrite):
                self.assertEqual(archive_id, "archive-1")
                self.assertFalse(overwrite)
                Path(output_path).write_text("restored", encoding="utf8")
                return {"output_path": output_path, "bytes_written": 8}

            readonly_files.download_file.side_effect = fake_download_file
            service = SyncService(readonly_records, Mock(), readonly_files, Mock(), runtime_store)

            result = service.restore_sync("session-1", key_id="agent-key", sync_id="syn_01")

            self.assertEqual(result["bytes_written"], 8)
            state = runtime_store.load()
            self.assertEqual(state.jobs[0].status, "synced")
            self.assertIsNotNone(state.jobs[0].last_downloaded_at)

    def test_restore_sync_accepts_local_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_store = SyncRuntimeStore(Path(tmpdir) / "syncs.json")
            local_path = Path(tmpdir) / "notes.txt"
            manifest = SyncManifest(
                key_id="agent-key",
                jobs=(
                    SyncJobConfig(
                        sync_id="syn_01",
                        space_id=1773,
                        local_path=str(local_path),
                        name="notes.txt",
                        archive_id="archive-1",
                    ),
                ),
            )
            readonly_records = Mock()
            readonly_records.list_spaces.return_value = {"spaces": [{"space_id": 1773, "writable": True}]}
            readonly_records.list_records.return_value = {
                "records": [
                    {
                        "title": reserved_sync_config_note_title("agent-key"),
                        "plain_text": manifest.to_note_text(),
                        "record_ref": "archive-notes:1",
                        "version": 1,
                    }
                ]
            }
            readonly_files = Mock()

            def fake_download_file(_session_id, *, archive_id, output_path, overwrite):
                self.assertEqual(archive_id, "archive-1")
                self.assertFalse(overwrite)
                Path(output_path).write_text("restored", encoding="utf8")
                return {"output_path": output_path, "bytes_written": 8}

            readonly_files.download_file.side_effect = fake_download_file
            service = SyncService(readonly_records, Mock(), readonly_files, Mock(), runtime_store)

            result = service.restore_sync("session-1", key_id="agent-key", sync_id=str(local_path))

            self.assertEqual(result["sync"]["sync_id"], "syn_01")
            self.assertEqual(result["bytes_written"], 8)

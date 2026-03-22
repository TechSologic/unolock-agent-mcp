from __future__ import annotations

from dataclasses import replace

from unolock_mcp.sync.config_note import SyncManifest
from unolock_mcp.sync.runtime_store import SyncRuntimeJob, SyncRuntimeState


def reconcile_manifests(
    manifests: list[SyncManifest],
    runtime_state: SyncRuntimeState | None = None,
) -> SyncRuntimeState:
    existing_jobs = {
        job.sync_id: job
        for job in (runtime_state.jobs if runtime_state is not None else ())
    }
    next_jobs: list[SyncRuntimeJob] = []
    seen_sync_ids: set[str] = set()
    seen_local_paths: dict[str, str] = {}

    for manifest in manifests:
        for config_job in manifest.jobs:
            if config_job.sync_id in seen_sync_ids:
                raise ValueError(f"Duplicate sync_id across sync manifests: {config_job.sync_id}")
            conflict_sync_id = seen_local_paths.get(config_job.local_path)
            if conflict_sync_id is not None:
                raise ValueError(
                    f"Local path is configured by multiple sync jobs: {config_job.local_path} "
                    f"({conflict_sync_id}, {config_job.sync_id})"
                )
            seen_sync_ids.add(config_job.sync_id)
            seen_local_paths[config_job.local_path] = config_job.sync_id
            existing = existing_jobs.get(config_job.sync_id)
            if existing is None:
                next_jobs.append(SyncRuntimeJob.from_config(config_job))
                continue
            next_jobs.append(
                replace(
                    existing,
                    space_id=config_job.space_id,
                    archive_id=config_job.archive_id or existing.archive_id,
                    local_path=config_job.local_path,
                    local_path_resolved=config_job.local_path,
                    name=config_job.name,
                    mime_type=config_job.mime_type,
                    mode=config_job.mode,
                    enabled=config_job.enabled,
                    poll_seconds=config_job.poll_seconds,
                    debounce_seconds=config_job.debounce_seconds,
                )
            )

    return SyncRuntimeState(
        version=(runtime_state.version if runtime_state is not None else 1),
        defaults=(runtime_state.defaults if runtime_state is not None else None),
        jobs=tuple(sorted(next_jobs, key=lambda job: (job.space_id, job.sync_id))),
    )

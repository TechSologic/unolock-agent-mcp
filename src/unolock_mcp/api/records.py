from __future__ import annotations

import base64
import hashlib
import json
from html.parser import HTMLParser
from typing import Any

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.auth.agent_auth import AgentAuthClient


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


class _UnoLockRecordsBase:
    def __init__(self, api_client: UnoLockApiClient, agent_auth: AgentAuthClient, session_store=None) -> None:
        self._api_client = api_client
        self._agent_auth = agent_auth
        self._session_store = session_store

    def _load_spaces(self, session_id: str, keyring) -> dict[int, dict[str, Any]]:
        response = self._api_client.get_spaces(session_id)
        spaces = self._unwrap_result_list(
            self._extract_result(response, expected_type="GetSpaces"),
            list_key="spaces",
        )
        if not isinstance(spaces, list):
            raise ValueError("GetSpaces returned an unexpected payload")

        resolved: dict[int, dict[str, Any]] = {}
        for space in spaces:
            if not isinstance(space, dict):
                continue
            sid = int(space.get("spaceID", 0) or 0)
            if sid <= 0:
                continue
            resolved[sid] = dict(space)
            if space.get("type") == "SHARED" and isinstance(space.get("wKey"), str) and space["wKey"]:
                key_b64 = keyring.decrypt_string(space["wKey"])
                keyring.init_space_keyring(sid, base64.b64decode(key_b64.encode("ascii")))
        return resolved

    def _load_archives(self, session_id: str, keyring) -> list[dict[str, Any]]:
        response = self._api_client.get_archives(session_id)
        archives = self._unwrap_result_list(
            self._extract_result(response, expected_type="GetArchives"),
            list_key="archives",
        )
        if not isinstance(archives, list):
            raise ValueError("GetArchives returned an unexpected payload")

        decrypted_archives: list[dict[str, Any]] = []
        for archive in archives:
            if not isinstance(archive, dict):
                continue
            current = dict(archive)
            sid = self._coerce_sid(current.get("sid"))
            metadata = current.get("m")
            if isinstance(metadata, str) and metadata:
                try:
                    current["m"] = json.loads(keyring.decrypt_string(metadata, sid=sid))
                except Exception:
                    current["m"] = None
            decrypted_archives.append(current)
        return decrypted_archives

    def _load_records_archive_blob(self, session_id: str, archive: dict[str, Any], keyring) -> dict[str, Any]:
        if archive.get("t") != "Records":
            raise ValueError("Archive is not a Records archive")
        metadata = archive.get("m")
        if not isinstance(metadata, dict):
            raise ValueError("Archive metadata is not available")
        if archive.get("nc") is False:
            raise ValueError("Compressed records archives are not supported by the MCP yet")

        archive_id = str(archive.get("id", ""))
        transfer_mode = str(metadata.get("tr", "post"))
        if transfer_mode == "lput":
            response = self._api_client.get_download_url(session_id, archive_id)
            url = self._extract_result(response, expected_type="GetDownloadUrl")
        else:
            response = self._api_client.get_regional_download_url(session_id, archive_id)
            url = self._extract_result(response, expected_type="GetRegionalDownloadUrl")

        if not isinstance(url, str) or not url:
            raise ValueError(f"Missing download URL for archive {archive_id}")

        encrypted, headers = self._api_client.http_client.get_text_with_headers_absolute(url)
        etag = headers.get("ETag") or headers.get("etag")
        kek = metadata.get("kek")
        sid = self._coerce_sid(archive.get("sid"))
        decrypted: str | None = None
        first_error: Exception | None = None
        try:
            decrypted = keyring.decrypt_string(encrypted, sid=sid)
        except Exception as exc:
            first_error = exc

        if decrypted is None and isinstance(kek, str) and kek:
            processed = keyring.xor_encrypted_data_keys_in_header_string(encrypted, kek)
            decrypted = keyring.decrypt_string(processed, sid=sid)

        if decrypted is None:
            raise first_error if first_error is not None else ValueError("Could not decrypt records archive")

        payload = json.loads(decrypted)
        if not isinstance(payload, dict):
            raise ValueError("Records archive payload is not an object")
        blob = {
            "body": payload,
            "etag": etag,
            "transfer_mode": transfer_mode,
            "archive_id": archive_id,
        }
        self._cache_records_archive_snapshot(session_id, archive, blob)
        return blob

    def _load_records_archive_body(self, session_id: str, archive: dict[str, Any], keyring) -> dict[str, Any]:
        return self._load_records_archive_blob(session_id, archive, keyring)["body"]

    def _project_record(
        self,
        record: dict[str, Any],
        archive: dict[str, Any],
        spaces: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        sid = self._coerce_sid(archive.get("sid"))
        is_checklist = bool(record.get("isCbox"))
        archive_meta = archive.get("m") if isinstance(archive.get("m"), dict) else {}
        labels = record.get("labels") if isinstance(record.get("labels"), list) else []
        checklist_items = self._project_checklist_items(record.get("checkBoxes"))
        plain_text = self._record_plain_text(record, checklist_items)
        read_only = bool(record.get("ro"))
        version = self._coerce_positive_int(record.get("version")) or 1
        return {
            "record_ref": self._build_record_ref(str(archive.get("id", "")), int(record.get("id", -1))),
            "id": int(record.get("id", -1)),
            "version": version,
            "archive_id": str(archive.get("id", "")),
            "space_id": sid,
            "space_name": str(archive_meta.get("spaceName", spaces.get(sid, {}).get("spaceName", ""))),
            "kind": "checklist" if is_checklist else "note",
            "title": str(record.get("recordTitle", "")),
            "plain_text": plain_text,
            "pinned": bool(record.get("pinned")),
            "labels": labels,
            "message_meta": record.get("messageMeta"),
            "checklist_items": checklist_items if is_checklist else [],
            "raw_delta": record.get("recordBody") if not is_checklist else None,
            "raw_checkboxes": record.get("checkBoxes") if is_checklist else [],
            "read_only": read_only,
            "locked": read_only,
        }

    def _project_checklist_items(self, checkboxes: Any) -> list[dict[str, Any]]:
        if not isinstance(checkboxes, list):
            return []
        items: list[dict[str, Any]] = []
        for index, checkbox in enumerate(checkboxes):
            if not isinstance(checkbox, dict):
                continue
            item_id = checkbox.get("id", index)
            try:
                numeric_id = int(item_id)
            except (TypeError, ValueError):
                numeric_id = index
            text = self._strip_html(str(checkbox.get("data", "")))
            done = bool(checkbox.get("done"))
            items.append(
                {
                    "id": numeric_id,
                    "text": text,
                    "done": done,
                    "checked": done,
                    "state": "checked" if done else "unchecked",
                    "order": index,
                }
            )
        return items

    def _record_plain_text(self, record: dict[str, Any], checklist_items: list[dict[str, Any]]) -> str:
        if bool(record.get("isCbox")):
            return "\n".join(item["text"] for item in checklist_items if item["text"])
        body = record.get("recordBody")
        if isinstance(body, str):
            delta_text = self._extract_text_from_delta(body)
            if delta_text is not None:
                return delta_text
            return self._strip_html(body).replace("\r\n", "\n").rstrip("\n")
        return ""

    def _extract_text_from_delta(self, value: str) -> str | None:
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        ops = parsed.get("ops")
        if not isinstance(ops, list):
            return None
        text = ""
        for op in ops:
            if not isinstance(op, dict):
                continue
            insert = op.get("insert")
            if isinstance(insert, str):
                text += insert
        return text.replace("\r\n", "\n").rstrip("\n")

    def _plain_text_to_delta(self, value: str) -> str:
        normalized = value.replace("\r\n", "\n")
        if not normalized.endswith("\n"):
            normalized += "\n"
        return json.dumps({"ops": [{"insert": normalized}]}, separators=(",", ":"))

    def _strip_html(self, value: str) -> str:
        parser = _HtmlTextExtractor()
        parser.feed(value)
        parser.close()
        return parser.get_text()

    def _extract_result(self, response: dict[str, Any], *, expected_type: str) -> Any:
        callback = response.get("callback", {})
        callback_type = callback.get("type")
        if callback_type == "FAILED":
            raise ValueError(f"{expected_type} failed: {callback.get('reason', 'UNKNOWN')}")
        if callback_type not in {expected_type, "SUCCESS"}:
            raise ValueError(f"Unexpected callback type for {expected_type}: {callback_type}")
        return callback.get("result")

    def _unwrap_result_list(self, result: Any, *, list_key: str) -> Any:
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            wrapped = result.get(list_key)
            if isinstance(wrapped, list):
                return wrapped
        return result

    def _parse_record_ref(self, record_ref: str) -> tuple[str, int]:
        archive_id, separator, raw_record_id = record_ref.partition(":")
        if not archive_id or separator != ":":
            raise ValueError("record_ref must be in the form <archive_id>:<record_id>")
        try:
            record_id = int(raw_record_id)
        except ValueError as exc:
            raise ValueError("record_ref must end with a numeric record_id") from exc
        return archive_id, record_id

    def _build_record_ref(self, archive_id: str, record_id: int) -> str:
        return f"{archive_id}:{record_id}"

    def _cache_records_archive_snapshot(self, session_id: str, archive: dict[str, Any], blob: dict[str, Any]) -> None:
        if self._session_store is None:
            return
        archive_id = str(archive.get("id", ""))
        if not archive_id:
            return
        self._session_store.put_records_archive_snapshot(
            session_id,
            archive_id,
            {
                "archive": archive,
                "body": blob["body"],
                "etag": blob["etag"],
                "transfer_mode": blob["transfer_mode"],
                "space_id": self._coerce_sid(archive.get("sid")),
            },
        )

    def _get_cached_records_archive_snapshot(
        self,
        session_id: str,
        archive_id: str,
        *,
        max_age_seconds: int | None = None,
    ) -> dict[str, Any]:
        if self._session_store is None:
            raise KeyError("No records archive cache is configured")
        return self._session_store.get_records_archive_snapshot(
            session_id,
            archive_id,
            max_age_seconds=max_age_seconds,
        )

    def _coerce_sid(self, value: Any) -> int | None:
        try:
            sid = int(value)
        except (TypeError, ValueError):
            return None
        return sid if sid > 0 else None

    def _coerce_positive_int(self, value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _label_names(self, projected_record: dict[str, Any]) -> set[str]:
        raw_labels = projected_record.get("labels")
        if not isinstance(raw_labels, list):
            return set()
        names: set[str] = set()
        for label in raw_labels:
            if isinstance(label, dict):
                name = str(label.get("name", "")).strip().lower()
                if name:
                    names.add(name)
        return names


class UnoLockReadonlyRecordsClient(_UnoLockRecordsBase):
    def list_records(
        self,
        session_id: str,
        kind: str = "all",
        *,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        normalized_kind = kind.strip().lower() if kind else "all"
        if normalized_kind not in {"all", "note", "checklist"}:
            raise ValueError("kind must be one of: all, note, checklist")
        normalized_label = label.strip().lower() if isinstance(label, str) and label.strip() else None

        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = self._load_archives(session_id, keyring)
        records: list[dict[str, Any]] = []

        for archive in archives:
            if archive.get("t") != "Records":
                continue
            if not isinstance(archive.get("m"), dict):
                continue
            body = self._load_records_archive_body(session_id, archive, keyring)
            data = body.get("data", {}) if isinstance(body, dict) else {}
            archive_records = data.get("records", [])
            if not isinstance(archive_records, list):
                continue
            for record in archive_records:
                if not isinstance(record, dict):
                    continue
                projected = self._project_record(record, archive, spaces)
                if normalized_kind != "all" and projected["kind"] != normalized_kind:
                    continue
                if space_id is not None and projected["space_id"] != space_id:
                    continue
                if pinned is not None and projected["pinned"] is not pinned:
                    continue
                if normalized_label is not None and normalized_label not in self._label_names(projected):
                    continue
                records.append(projected)

        records.sort(key=lambda item: (item["space_id"], item["id"]))
        return {
            "kind_filter": normalized_kind,
            "space_id_filter": space_id,
            "pinned_filter": pinned,
            "label_filter": normalized_label,
            "count": len(records),
            "records": records,
        }

    def list_spaces(self, session_id: str) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = self._load_archives(session_id, keyring)
        summaries: dict[int, dict[str, Any]] = {}

        for sid, space in spaces.items():
            summaries[sid] = {
                "space_id": sid,
                "type": space.get("type", "PRIVATE"),
                "owner": bool(space.get("owner")),
                "space_name": "",
                "record_archive_id": None,
                "record_count": 0,
                "note_count": 0,
                "checklist_count": 0,
            }

        for archive in archives:
            if archive.get("t") != "Records":
                continue
            sid = self._coerce_sid(archive.get("sid"))
            if sid is None:
                continue
            summary = summaries.setdefault(
                sid,
                {
                    "space_id": sid,
                    "type": spaces.get(sid, {}).get("type", "PRIVATE"),
                    "owner": bool(spaces.get(sid, {}).get("owner")),
                    "space_name": "",
                    "record_archive_id": None,
                    "record_count": 0,
                    "note_count": 0,
                    "checklist_count": 0,
                },
            )
            summary["record_archive_id"] = archive.get("id")
            metadata = archive.get("m")
            if isinstance(metadata, dict):
                summary["space_name"] = str(metadata.get("spaceName", "")).strip()
                body = self._load_records_archive_body(session_id, archive, keyring)
                data = body.get("data", {}) if isinstance(body, dict) else {}
                archive_records = data.get("records", [])
                if isinstance(archive_records, list):
                    summary["record_count"] = len([record for record in archive_records if isinstance(record, dict)])
                    summary["checklist_count"] = len(
                        [
                            record
                            for record in archive_records
                            if isinstance(record, dict) and bool(record.get("isCbox"))
                        ]
                    )
                    summary["note_count"] = summary["record_count"] - summary["checklist_count"]

        ordered = sorted(summaries.values(), key=lambda item: item["space_id"])
        return {
            "count": len(ordered),
            "spaces": ordered,
        }

    def get_record(self, session_id: str, record_ref: str) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = {archive["id"]: archive for archive in self._load_archives(session_id, keyring)}
        archive = archives.get(archive_id)
        if archive is None:
            raise ValueError(f"Unknown archive id in record_ref: {archive_id}")
        try:
            body = self._get_cached_records_archive_snapshot(
                session_id,
                archive_id,
                max_age_seconds=self._session_store.RECORDS_ARCHIVE_CACHE_TTL_SECONDS if self._session_store else None,
            )["body"]
        except KeyError:
            body = self._load_records_archive_body(session_id, archive, keyring)
        data = body.get("data", {}) if isinstance(body, dict) else {}
        archive_records = data.get("records", [])
        if not isinstance(archive_records, list):
            raise ValueError("Archive did not contain a records array")
        for record in archive_records:
            if isinstance(record, dict) and int(record.get("id", -1)) == record_id:
                return self._project_record(record, archive, spaces)
        raise ValueError(f"Record not found for record_ref: {record_ref}")


class UnoLockWritableRecordsClient(_UnoLockRecordsBase):
    def create_note(self, session_id: str, *, space_id: int, title: str, text: str) -> dict[str, Any]:
        return self._create_record(
            session_id,
            space_id=space_id,
            title=title,
            record_factory=lambda record_id: {
                "id": record_id,
                "version": 1,
                "recordTitle": title,
                "recordBody": self._plain_text_to_delta(text),
                "pinned": False,
                "bgColor": "",
                "bgImage": "",
                "color": "",
                "isCbox": False,
                "labels": [],
                "archives": None,
                "wallet": None,
                "ro": False,
            },
        )

    def create_checklist(self, session_id: str, *, space_id: int, title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        normalized_items = self._normalize_checklist_create_items(items)
        return self._create_record(
            session_id,
            space_id=space_id,
            title=title,
            record_factory=lambda record_id: {
                "id": record_id,
                "version": 1,
                "recordTitle": title,
                "recordBody": "",
                "pinned": False,
                "bgColor": "",
                "bgImage": "",
                "color": "",
                "isCbox": True,
                "labels": [],
                "archives": None,
                "wallet": None,
                "ro": False,
                "checkBoxes": [
                    {"id": index, "data": item["text"], "done": item["done"]}
                    for index, item in enumerate(normalized_items)
                ],
            },
        )

    def update_note(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        title: str,
        text: str,
    ) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        expected_version = self._coerce_positive_int(expected_version) or 0
        if expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")

        try:
            write_context = self._get_cached_write_context_for_archive(session_id, archive_id)
        except KeyError as exc:
            raise ValueError(
                "No cached archive state is available for this record. Read the note first, then retry the update."
            ) from exc

        for _ in range(2):
            body = write_context["body"]
            archive = write_context["archive"]
            target_record = self._require_record(body, record_id)

            if bool(target_record.get("isCbox")):
                raise ValueError("record_ref does not point to a note")
            if bool(target_record.get("ro")):
                raise ValueError("record_locked")

            current_version = self._coerce_positive_int(target_record.get("version")) or 1
            if current_version != expected_version:
                raise ValueError("Write conflict requires reread")

            target_record["recordTitle"] = title
            target_record["recordBody"] = self._plain_text_to_delta(text)
            target_record["version"] = current_version + 1

            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    write_context = self._load_write_context_for_archive(session_id, archive_id)
                    continue
                raise

            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(target_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def rename_record(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        title: str,
    ) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        expected_version = self._coerce_positive_int(expected_version) or 0
        if expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")

        try:
            write_context = self._get_cached_write_context_for_archive(session_id, archive_id)
        except KeyError as exc:
            raise ValueError(
                "No cached archive state is available for this record. Read the record first, then retry the rename."
            ) from exc

        for _ in range(2):
            body = write_context["body"]
            archive = write_context["archive"]
            target_record = self._require_record(body, record_id)

            if bool(target_record.get("ro")):
                raise ValueError("record_locked")

            current_version = self._coerce_positive_int(target_record.get("version")) or 1
            if current_version != expected_version:
                raise ValueError("Write conflict requires reread")

            target_record["recordTitle"] = title
            target_record["version"] = current_version + 1

            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    write_context = self._load_write_context_for_archive(session_id, archive_id)
                    continue
                raise

            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(target_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def set_checklist_item_done(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        item_id: int,
        done: bool,
    ) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        expected_version = self._coerce_positive_int(expected_version) or 0
        if expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")

        try:
            write_context = self._get_cached_write_context_for_archive(session_id, archive_id)
        except KeyError as exc:
            raise ValueError(
                "No cached archive state is available for this record. Read the checklist first, then retry the update."
            ) from exc

        for _ in range(2):
            body = write_context["body"]
            archive = write_context["archive"]
            target_record = self._require_record(body, record_id)

            if not bool(target_record.get("isCbox")):
                raise ValueError("record_ref does not point to a checklist")
            if bool(target_record.get("ro")):
                raise ValueError("record_locked")

            current_version = self._coerce_positive_int(target_record.get("version")) or 1
            if current_version != expected_version:
                raise ValueError("Write conflict requires reread")

            checkboxes = target_record.get("checkBoxes")
            if not isinstance(checkboxes, list):
                raise ValueError("Checklist payload is invalid")

            target_item = None
            for checkbox in checkboxes:
                if not isinstance(checkbox, dict):
                    continue
                try:
                    current_item_id = int(checkbox.get("id", -1))
                except (TypeError, ValueError):
                    continue
                if current_item_id == item_id:
                    target_item = checkbox
                    break
            if target_item is None:
                raise ValueError("Checklist item not found")

            target_item["done"] = bool(done)
            target_record["version"] = current_version + 1

            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    write_context = self._load_write_context_for_archive(session_id, archive_id)
                    continue
                raise

            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(target_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def add_checklist_item(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        text: str,
    ) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        expected_version = self._coerce_positive_int(expected_version) or 0
        if expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("Checklist item text must not be empty")

        try:
            write_context = self._get_cached_write_context_for_archive(session_id, archive_id)
        except KeyError as exc:
            raise ValueError(
                "No cached archive state is available for this record. Read the checklist first, then retry the update."
            ) from exc

        for _ in range(2):
            body = write_context["body"]
            archive = write_context["archive"]
            target_record, checkboxes, current_version = self._prepare_checklist_mutation(
                body,
                record_id,
                expected_version,
            )

            next_item_id = self._next_checklist_item_id(checkboxes)
            checkboxes.append({"id": next_item_id, "data": normalized_text, "done": False})
            target_record["version"] = current_version + 1

            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    write_context = self._load_write_context_for_archive(session_id, archive_id)
                    continue
                raise

            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(target_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def remove_checklist_item(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        item_id: int,
    ) -> dict[str, Any]:
        archive_id, record_id = self._parse_record_ref(record_ref)
        expected_version = self._coerce_positive_int(expected_version) or 0
        if expected_version <= 0:
            raise ValueError("expected_version must be a positive integer")

        try:
            write_context = self._get_cached_write_context_for_archive(session_id, archive_id)
        except KeyError as exc:
            raise ValueError(
                "No cached archive state is available for this record. Read the checklist first, then retry the update."
            ) from exc

        for _ in range(2):
            body = write_context["body"]
            archive = write_context["archive"]
            target_record, checkboxes, current_version = self._prepare_checklist_mutation(
                body,
                record_id,
                expected_version,
            )

            target_index = self._find_checklist_item_index(checkboxes, item_id)
            if target_index is None:
                raise ValueError("Checklist item not found")
            checkboxes.pop(target_index)
            target_record["version"] = current_version + 1

            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    write_context = self._load_write_context_for_archive(session_id, archive_id)
                    continue
                raise

            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(target_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def _normalize_checklist_create_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each checklist item must be an object")
            text = ""
            done = False
            raw_text = item.get("text")
            if isinstance(raw_text, str):
                text = raw_text.strip()
            else:
                raise ValueError("Each checklist item must include a text string")
            if "done" in item:
                done = bool(item.get("done"))
            elif "checked" in item:
                done = bool(item.get("checked"))
            elif "state" in item:
                done = str(item.get("state", "")).strip().lower() == "checked"
            if text:
                normalized.append({"text": text, "done": done})
            else:
                raise ValueError("Checklist item text must not be empty")
        return normalized

    def _create_record(
        self,
        session_id: str,
        *,
        space_id: int,
        title: str,
        record_factory,
    ) -> dict[str, Any]:
        for _ in range(2):
            write_context = self._load_write_context(session_id, space_id)
            body = write_context["body"]
            archive = write_context["archive"]
            records_data = body.setdefault("data", {})
            current_records = records_data.setdefault("records", [])
            if not isinstance(current_records, list):
                raise ValueError("Records archive payload is invalid")
            next_record_id = int(records_data.get("nextRecordID", 0) or 0) + 1
            records_data["nextRecordID"] = next_record_id
            records_data.setdefault("nextLabelID", 0)
            records_data.setdefault("labels", [])
            new_record = record_factory(next_record_id)
            current_records.append(new_record)
            try:
                self._upload_records_archive(session_id, write_context)
            except ValueError as exc:
                if "conflict" in str(exc).lower():
                    continue
                raise
            keyring = self._agent_auth.get_keyring_for_session(session_id)
            spaces = self._load_spaces(session_id, keyring)
            return {
                "ok": True,
                "record": self._project_record(new_record, archive, spaces),
            }
        raise ValueError("Write conflict requires reread")

    def _load_write_context(self, session_id: str, space_id: int) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        spaces = self._load_spaces(session_id, keyring)
        archives = self._load_archives(session_id, keyring)
        archive = next(
            (
                current
                for current in archives
                if current.get("t") == "Records" and self._coerce_sid(current.get("sid")) == space_id
            ),
            None,
        )
        if archive is None:
            raise ValueError("No writable Records archive exists for the requested space")
        blob = self._load_records_archive_blob(session_id, archive, keyring)
        return {
            "archive": archive,
            "body": blob["body"],
            "etag": blob["etag"],
            "transfer_mode": blob["transfer_mode"],
            "keyring": keyring,
            "space_id": space_id,
        }

    def _load_write_context_for_archive(self, session_id: str, archive_id: str) -> dict[str, Any]:
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        archives = self._load_archives(session_id, keyring)
        archive = next(
            (
                current
                for current in archives
                if current.get("t") == "Records" and str(current.get("id", "")) == archive_id
            ),
            None,
        )
        if archive is None:
            raise ValueError(f"Unknown archive id in record_ref: {archive_id}")
        blob = self._load_records_archive_blob(session_id, archive, keyring)
        return {
            "archive": archive,
            "body": blob["body"],
            "etag": blob["etag"],
            "transfer_mode": blob["transfer_mode"],
            "keyring": keyring,
            "space_id": self._coerce_sid(archive.get("sid")),
        }

    def _get_cached_write_context_for_archive(self, session_id: str, archive_id: str) -> dict[str, Any]:
        snapshot = self._get_cached_records_archive_snapshot(session_id, archive_id)
        keyring = self._agent_auth.get_keyring_for_session(session_id)
        return {
            "archive": snapshot["archive"],
            "body": snapshot["body"],
            "etag": snapshot["etag"],
            "transfer_mode": snapshot["transfer_mode"],
            "keyring": keyring,
            "space_id": snapshot["space_id"],
        }

    def _require_record(self, body: dict[str, Any], record_id: int) -> dict[str, Any]:
        data = body.setdefault("data", {})
        current_records = data.setdefault("records", [])
        if not isinstance(current_records, list):
            raise ValueError("Records archive payload is invalid")
        for record in current_records:
            if isinstance(record, dict) and int(record.get("id", -1)) == record_id:
                return record
        raise ValueError("Record not found for record_ref")

    def _prepare_checklist_mutation(
        self,
        body: dict[str, Any],
        record_id: int,
        expected_version: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        target_record = self._require_record(body, record_id)

        if not bool(target_record.get("isCbox")):
            raise ValueError("record_ref does not point to a checklist")
        if bool(target_record.get("ro")):
            raise ValueError("record_locked")

        current_version = self._coerce_positive_int(target_record.get("version")) or 1
        if current_version != expected_version:
            raise ValueError("Write conflict requires reread")

        checkboxes = target_record.get("checkBoxes")
        if not isinstance(checkboxes, list):
            raise ValueError("Checklist payload is invalid")
        return target_record, checkboxes, current_version

    def _find_checklist_item_index(self, checkboxes: list[dict[str, Any]], item_id: int) -> int | None:
        for index, checkbox in enumerate(checkboxes):
            if not isinstance(checkbox, dict):
                continue
            try:
                current_item_id = int(checkbox.get("id", -1))
            except (TypeError, ValueError):
                continue
            if current_item_id == item_id:
                return index
        return None

    def _next_checklist_item_id(self, checkboxes: list[dict[str, Any]]) -> int:
        used_ids: set[int] = set()
        for checkbox in checkboxes:
            if not isinstance(checkbox, dict):
                continue
            try:
                used_ids.add(int(checkbox.get("id", -1)))
            except (TypeError, ValueError):
                continue
        next_item_id = 0
        while next_item_id in used_ids:
            next_item_id += 1
        return next_item_id

    def _upload_records_archive(self, session_id: str, context: dict[str, Any]) -> None:
        archive = context["archive"]
        body = context["body"]
        transfer_mode = context["transfer_mode"]
        keyring = context["keyring"]
        space_id = context["space_id"]
        if space_id is None:
            raise ValueError("Archive is not associated with a valid space")
        if transfer_mode != "lput":
            raise ValueError(f"Unsupported archive transfer mode for writes: {transfer_mode}")

        serialized = json.dumps(body, separators=(",", ":"))
        encrypted = keyring.encrypt_string(serialized, sid=space_id)
        metadata = archive.get("m") if isinstance(archive.get("m"), dict) else {}
        current_kek = metadata.get("kek")
        encrypted, updated_kek = keyring.apply_kek_to_encrypted_data_keys_string(encrypted, current_kek)
        if updated_kek != current_kek:
            next_archive = dict(archive)
            next_metadata = dict(metadata)
            next_metadata["kek"] = updated_kek
            next_archive["m"] = next_metadata
            self._extract_result(
                self._api_client.update_archive(session_id, next_archive),
                expected_type="UpdateArchive",
            )
            archive["m"] = next_metadata

        payload_bytes = encrypted.encode("utf8")
        md5_bytes = hashlib.md5(payload_bytes).digest()
        md5_hex = md5_bytes.hex()
        md5_b64 = base64.b64encode(md5_bytes).decode("ascii")
        new_etag = f"\"{md5_hex}\""
        current_etag = context.get("etag")
        upload_url = self._extract_result(
            self._api_client.get_upload_put_url(
                session_id,
                archive_id=str(archive.get("id", "")),
                md5_b64=md5_b64,
                current_etag=current_etag,
                new_etag=new_etag,
            ),
            expected_type="GetUploadPutUrl",
        )
        if not isinstance(upload_url, str) or not upload_url:
            raise ValueError("Missing upload URL for records archive write")
        headers = {"Content-MD5": md5_b64}
        if current_etag:
            headers["If-Match"] = current_etag
        try:
            result = self._api_client.http_client.put_bytes_absolute(upload_url, payload_bytes, headers=headers)
        except Exception as exc:
            message = str(exc)
            if "412" in message or "409" in message:
                raise ValueError("Write conflict requires reread") from exc
            raise
        returned_etag = result["headers"].get("ETag") or result["headers"].get("etag")
        if returned_etag and returned_etag != new_etag:
            raise ValueError("Write conflict requires reread")
        context["etag"] = returned_etag or new_etag
        self._cache_records_archive_snapshot(
            session_id,
            archive,
            {
                "body": body,
                "etag": context["etag"],
                "transfer_mode": transfer_mode,
                "archive_id": str(archive.get("id", "")),
            },
        )

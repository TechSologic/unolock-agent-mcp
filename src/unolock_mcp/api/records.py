from __future__ import annotations

import base64
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


class UnoLockReadonlyRecordsClient:
    def __init__(self, api_client: UnoLockApiClient, agent_auth: AgentAuthClient) -> None:
        self._api_client = api_client
        self._agent_auth = agent_auth

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
        body = self._load_records_archive_body(session_id, archive, keyring)
        data = body.get("data", {}) if isinstance(body, dict) else {}
        archive_records = data.get("records", [])
        if not isinstance(archive_records, list):
            raise ValueError("Archive did not contain a records array")
        for record in archive_records:
            if isinstance(record, dict) and int(record.get("id", -1)) == record_id:
                return self._project_record(record, archive, spaces)
        raise ValueError(f"Record not found for record_ref: {record_ref}")

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

    def _load_records_archive_body(self, session_id: str, archive: dict[str, Any], keyring) -> dict[str, Any]:
        if archive.get("t") != "Records":
            raise ValueError("Archive is not a Records archive")
        metadata = archive.get("m")
        if not isinstance(metadata, dict):
            raise ValueError("Archive metadata is not available")
        if archive.get("nc") is False:
            raise ValueError("Compressed records archives are not supported in the read-only MCP yet")

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

        encrypted = self._api_client.http_client.get_text_absolute(url)
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
        return payload

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
        return {
            "record_ref": self._build_record_ref(str(archive.get("id", "")), int(record.get("id", -1))),
            "id": int(record.get("id", -1)),
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
            items.append(
                {
                    "id": numeric_id,
                    "text": text,
                    "done": bool(checkbox.get("done")),
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

    def _coerce_sid(self, value: Any) -> int | None:
        try:
            sid = int(value)
        except (TypeError, ValueError):
            return None
        return sid if sid > 0 else None

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

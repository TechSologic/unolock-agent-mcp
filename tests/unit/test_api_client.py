from __future__ import annotations

import unittest
from unittest.mock import Mock

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.domain.models import CallbackAction, FlowSession


class UnoLockApiClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.flow_client = Mock()
        self.session_store = Mock()
        self.client = UnoLockApiClient(self.flow_client, self.session_store)
        self.session = FlowSession(
            session_id="session-1",
            flow="agentAccess",
            state="state-1",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="SUCCESS", result={"ok": True}),
            authorized=True,
        )
        self.updated_session = FlowSession(
            session_id="session-1",
            flow="agentAccess",
            state="state-2",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="GetSpaces", result={"spaces": []}),
            authorized=True,
        )
        self.callback = CallbackAction(type="GetSpaces", result={"spaces": []})

    def test_call_action_updates_session_store_and_returns_callback_payload(self) -> None:
        self.session_store.get.return_value = self.session
        self.flow_client.call_api.return_value = (self.updated_session, self.callback)

        result = self.client.call_action("session-1", action="GetSpaces", request={"x": 1})

        self.session_store.get.assert_called_once_with("session-1")
        self.flow_client.call_api.assert_called_once_with(
            self.session,
            action="GetSpaces",
            request={"x": 1},
            result=None,
            reason=None,
            message=None,
        )
        self.session_store.put.assert_called_once_with(self.updated_session)
        self.assertEqual(result["session"]["current_callback_type"], "GetSpaces")
        self.assertEqual(result["callback"]["type"], "GetSpaces")

    def test_get_upload_put_url_includes_optional_etags(self) -> None:
        self.client.call_action = Mock(return_value={"ok": True})  # type: ignore[method-assign]

        result = self.client.get_upload_put_url(
            "session-1",
            "archive-1",
            "md5-b64",
            current_etag='"old"',
            new_etag='"new"',
        )

        self.client.call_action.assert_called_once_with(  # type: ignore[attr-defined]
            "session-1",
            action="GetUploadPutUrl",
            request={"archiveID": "archive-1", "md5": "md5-b64", "currentEtag": '"old"', "newEtag": '"new"'},
        )
        self.assertEqual(result, {"ok": True})

    def test_get_upload_post_object_uses_archive_id_request(self) -> None:
        self.client.call_action = Mock(return_value={"ok": True})  # type: ignore[method-assign]

        self.client.get_upload_post_object("session-1", "archive-9")

        self.client.call_action.assert_called_once_with(  # type: ignore[attr-defined]
            "session-1",
            action="GetUploadPostObject",
            request="archive-9",
        )

    def test_http_client_property_proxies_flow_client(self) -> None:
        self.flow_client.http_client = object()

        self.assertIs(self.client.http_client, self.flow_client.http_client)


if __name__ == "__main__":
    unittest.main()

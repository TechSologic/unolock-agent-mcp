from __future__ import annotations

import unittest

from unolock_mcp.transport.callback_codec import CallbackDtoCodec


class CallbackDtoCodecTest(unittest.TestCase):
    def test_defaults_reason_to_none_for_agent_and_access_callbacks(self) -> None:
        self.assertEqual(CallbackDtoCodec.default_reason("AgentChallenge"), "NONE")
        self.assertEqual(CallbackDtoCodec.default_reason("GetSafeAccessID"), "NONE")
        self.assertEqual(CallbackDtoCodec.default_reason("DecodeKey"), "NONE")

    def test_defaults_reason_to_empty_for_pq_exchange(self) -> None:
        self.assertEqual(CallbackDtoCodec.default_reason("PQ_KEY_EXCHANGE"), "")

    def test_explicit_reason_wins(self) -> None:
        self.assertEqual(CallbackDtoCodec.default_reason("AgentChallenge", ""), "")
        self.assertEqual(CallbackDtoCodec.default_reason("PQ_KEY_EXCHANGE", "NONE"), "NONE")


if __name__ == "__main__":
    unittest.main()

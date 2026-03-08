from __future__ import annotations

import unittest

from unolock_mcp.crypto.safe_keyring import SafeKeyringManager


class SafeKeyringManagerTest(unittest.TestCase):
    def test_can_encrypt_and_decrypt_default_and_shared_space_strings(self) -> None:
        keyring = SafeKeyringManager()
        keyring.init_with_safe_access_master_key(bytes(range(32)))
        keyring.init_space_keyring(7, bytes(range(32, 64)))

        default_encrypted = keyring.encrypt_string("default text")
        shared_encrypted = keyring.encrypt_string("shared text", sid=7)

        self.assertEqual(keyring.decrypt_string(default_encrypted), "default text")
        self.assertEqual(keyring.decrypt_string(shared_encrypted, sid=7), "shared text")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from .base import CreatedKey, KeyBindingInfo, TpmDao, TpmDiagnostics


MACOS_SECURE_ENCLAVE_HELPER = r"""
import Foundation
import Security

func jsonOut(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj, options: []),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    } else {
        print("{\"ok\":false,\"error\":\"json_encode_failed\"}")
    }
}

func dataToBase64(_ data: Data) -> String {
    data.base64EncodedString()
}

func bindingInfo() -> [String: Any] {
    [
        "protection": "mac-secure-enclave",
        "exportable": false,
        "attestation_supported": false,
        "device_binding": "hardware:secure-enclave",
    ]
}

func keyTag(_ name: String) -> Data {
    "com.unolock.agent.\(name)".data(using: .utf8)!
}

func secretService(_ name: String) -> String {
    "com.unolock.agent.secret.\(name)"
}

func makeAccessControl() throws -> SecAccessControl {
    var error: Unmanaged<CFError>?
    guard let ac = SecAccessControlCreateWithFlags(
        nil,
        kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        [.privateKeyUsage],
        &error
    ) else {
        throw error!.takeRetainedValue() as Error
    }
    return ac
}

func createKey(_ name: String) throws -> [String: Any] {
    let tag = keyTag(name)
    let query: [String: Any] = [
        kSecClass as String: kSecClassKey,
        kSecAttrApplicationTag as String: tag,
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecReturnRef as String: true,
    ]
    var existing: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &existing)
    let privateKey: SecKey
    if status == errSecSuccess, let key = existing {
        privateKey = (key as! SecKey)
    } else {
        let ac = try makeAccessControl()
        let attributes: [String: Any] = [
            kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
            kSecAttrKeySizeInBits as String: 256,
            kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,
            kSecPrivateKeyAttrs as String: [
                kSecAttrIsPermanent as String: true,
                kSecAttrApplicationTag as String: tag,
                kSecAttrAccessControl as String: ac,
            ],
        ]
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateRandomKey(attributes as CFDictionary, &error) else {
            throw error!.takeRetainedValue() as Error
        }
        privateKey = key
    }

    guard let publicKey = SecKeyCopyPublicKey(privateKey) else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: 1, userInfo: [NSLocalizedDescriptionKey: "missing_public_key"])
    }
    var exportError: Unmanaged<CFError>?
    guard let publicBytes = SecKeyCopyExternalRepresentation(publicKey, &exportError) as Data? else {
        throw exportError!.takeRetainedValue() as Error
    }
    return [
        "ok": true,
        "key_id": name,
        "public_key_b64": dataToBase64(publicBytes),
        "binding_info": bindingInfo(),
    ]
}

func getPublicKey(_ name: String) throws -> [String: Any] {
    let created = try createKey(name)
    return [
        "ok": true,
        "public_key_b64": created["public_key_b64"]!,
    ]
}

func sign(_ name: String, _ challengeB64: String) throws -> [String: Any] {
    let tag = keyTag(name)
    let query: [String: Any] = [
        kSecClass as String: kSecClassKey,
        kSecAttrApplicationTag as String: tag,
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecReturnRef as String: true,
    ]
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    guard status == errSecSuccess, let privateKey = item as! SecKey? else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "key_not_found"])
    }
    guard let challenge = Data(base64Encoded: challengeB64) else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: 2, userInfo: [NSLocalizedDescriptionKey: "invalid_challenge_b64"])
    }
    var error: Unmanaged<CFError>?
    guard let signature = SecKeyCreateSignature(
        privateKey,
        .ecdsaSignatureMessageX962SHA256,
        challenge as CFData,
        &error
    ) as Data? else {
        throw error!.takeRetainedValue() as Error
    }
    return [
        "ok": true,
        "signature_b64": dataToBase64(signature),
    ]
}

func deleteKey(_ name: String) -> [String: Any] {
    let tag = keyTag(name)
    let query: [String: Any] = [
        kSecClass as String: kSecClassKey,
        kSecAttrApplicationTag as String: tag,
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
    ]
    SecItemDelete(query as CFDictionary)
    return [
        "ok": true,
        "deleted": name,
    ]
}

func storeSecret(_ name: String, _ secretB64: String) throws -> [String: Any] {
    guard let secret = Data(base64Encoded: secretB64) else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: 6, userInfo: [NSLocalizedDescriptionKey: "invalid_secret_b64"])
    }
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: secretService(name),
        kSecAttrAccount as String: name,
        kSecValueData as String: secret,
        kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
    ]
    SecItemDelete(query as CFDictionary)
    let status = SecItemAdd(query as CFDictionary, nil)
    guard status == errSecSuccess else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "secret_store_failed"])
    }
    return [
        "ok": true,
        "stored": name,
    ]
}

func loadSecret(_ name: String) throws -> [String: Any] {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: secretService(name),
        kSecAttrAccount as String: name,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecItemNotFound {
        return [
            "ok": true,
            "secret_b64": "",
        ]
    }
    guard status == errSecSuccess, let data = item as? Data else {
        throw NSError(domain: "UnoLockMacSecureEnclave", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "secret_load_failed"])
    }
    return [
        "ok": true,
        "secret_b64": dataToBase64(data),
    ]
}

func deleteSecret(_ name: String) -> [String: Any] {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: secretService(name),
        kSecAttrAccount as String: name,
    ]
    SecItemDelete(query as CFDictionary)
    return [
        "ok": true,
        "deleted_secret": name,
    ]
}

func diagnose() throws -> [String: Any] {
    let testName = "UnoLockDiag-\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))"
    let created = try createKey(testName)
    _ = deleteKey(testName)
    return [
        "ok": true,
        "available": true,
        "provider_name": "mac-secure-enclave",
        "summary": "Secure Enclave created a non-exportable P-256 key.",
        "binding_info": bindingInfo(),
        "public_key_b64": created["public_key_b64"]!,
    ]
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    jsonOut(["ok": false, "error": "missing_action"])
    exit(1)
}

let action = args[1]

do {
    switch action {
    case "diagnose":
        jsonOut(try diagnose())
    case "create-key":
        guard args.count >= 3 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing_key_name"])
        }
        jsonOut(try createKey(args[2]))
    case "get-public-key":
        guard args.count >= 3 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing_key_name"])
        }
        jsonOut(try getPublicKey(args[2]))
    case "sign":
        guard args.count >= 4 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 4, userInfo: [NSLocalizedDescriptionKey: "missing_sign_args"])
        }
        jsonOut(try sign(args[2], args[3]))
    case "delete-key":
        guard args.count >= 3 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing_key_name"])
        }
        jsonOut(deleteKey(args[2]))
    case "store-secret":
        guard args.count >= 4 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 7, userInfo: [NSLocalizedDescriptionKey: "missing_secret_args"])
        }
        jsonOut(try storeSecret(args[2], args[3]))
    case "load-secret":
        guard args.count >= 3 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing_key_name"])
        }
        jsonOut(try loadSecret(args[2]))
    case "delete-secret":
        guard args.count >= 3 else {
            throw NSError(domain: "UnoLockMacSecureEnclave", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing_key_name"])
        }
        jsonOut(deleteSecret(args[2]))
    default:
        throw NSError(domain: "UnoLockMacSecureEnclave", code: 5, userInfo: [NSLocalizedDescriptionKey: "unknown_action"])
    }
} catch {
    jsonOut([
        "ok": false,
        "error": error.localizedDescription,
        "action": action,
    ])
    exit(1)
}
"""


class MacSecureEnclaveDao(TpmDao):
    def __init__(self, swift_path: str | None = None) -> None:
        self._swift = swift_path or shutil.which("swift") or shutil.which("xcrun")
        self._swiftc = shutil.which("swiftc") or (self._swift if self._swift and Path(self._swift).name == "xcrun" else None)

    def provider_name(self) -> str:
        return "mac-secure-enclave"

    def create_key(self, key_id: str) -> CreatedKey:
        payload = self._run_helper("create-key", key_id=key_id)
        return CreatedKey(
            key_id=str(payload["key_id"]),
            public_key=base64.b64decode(str(payload["public_key_b64"]).encode("ascii")),
            binding_info=self._binding_info_from_payload(payload["binding_info"]),
        )

    def get_public_key(self, key_id: str) -> bytes:
        payload = self._run_helper("get-public-key", key_id=key_id)
        return base64.b64decode(str(payload["public_key_b64"]).encode("ascii"))

    def sign(self, key_id: str, challenge: bytes) -> bytes:
        payload = self._run_helper(
            "sign",
            key_id=key_id,
            challenge_b64=base64.b64encode(challenge).decode("ascii"),
        )
        return self._normalize_signature(base64.b64decode(str(payload["signature_b64"]).encode("ascii")))

    def get_binding_info(self, key_id: str) -> KeyBindingInfo:
        created = self.create_key(key_id)
        return created.binding_info

    def delete_key(self, key_id: str) -> None:
        self._run_helper("delete-key", key_id=key_id)

    def store_secret(self, secret_id: str, secret: bytes) -> None:
        self._run_helper(
            "store-secret",
            key_id=secret_id,
            challenge_b64=base64.b64encode(secret).decode("ascii"),
        )

    def load_secret(self, secret_id: str) -> bytes | None:
        payload = self._run_helper("load-secret", key_id=secret_id)
        secret_b64 = str(payload.get("secret_b64", ""))
        if not secret_b64:
            return None
        return base64.b64decode(secret_b64.encode("ascii"))

    def delete_secret(self, secret_id: str) -> None:
        self._run_helper("delete-secret", key_id=secret_id)

    def diagnose(self) -> TpmDiagnostics:
        details = {
            "os": platform.system().lower(),
            "release": platform.release().lower(),
            "swift_path": self._swift,
        }
        advice: list[str] = []
        if platform.system().lower() != "darwin":
            advice.append("Secure Enclave is only available on macOS.")
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=False,
                available=False,
                summary="macOS Secure Enclave is not available on this host.",
                details=details,
                advice=advice,
            )
        if not self._swift:
            advice.append("Install Xcode command line tools so the MCP can run the Secure Enclave helper.")
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=False,
                available=False,
                summary="Swift tooling is not available on this macOS host.",
                details=details,
                advice=advice,
            )
        try:
            payload = self._run_helper("diagnose")
            details["binding_info"] = payload.get("binding_info")
            advice.append("Keep this provider selected for production use on macOS.")
            advice.append("Test on a real Secure Enclave-capable Mac before broad rollout.")
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=True,
                available=True,
                summary=str(payload.get("summary", "Secure Enclave provider is available.")),
                details=details,
                advice=advice,
            )
        except Exception as exc:
            details["error"] = str(exc)
            advice.extend(self._diagnostic_advice_for_exception(exc))
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=False,
                available=False,
                summary=self._diagnostic_summary_for_exception(exc),
                details=details,
                advice=advice,
            )

    def _run_helper(
        self,
        action: str,
        *,
        key_id: str | None = None,
        challenge_b64: str | None = None,
    ) -> dict[str, object]:
        if not self._swift:
            raise RuntimeError("swift or xcrun is not available")
        helper_binary = self._ensure_compiled_helper()
        if helper_binary:
            command = [str(helper_binary)]
            if action:
                command.append(action)
            if key_id is not None:
                command.append(key_id)
            if challenge_b64 is not None:
                command.append(challenge_b64)
            proc = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if not stdout:
                raise RuntimeError(stderr or "macOS Secure Enclave helper returned no output")
            payload = json.loads(stdout)
            if proc.returncode != 0 or not payload.get("ok"):
                raise RuntimeError(str(payload.get("error") or stderr or "macOS Secure Enclave helper failed"))
            return payload

        with tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False, encoding="utf8") as handle:
            script_path = Path(handle.name)
            handle.write(MACOS_SECURE_ENCLAVE_HELPER)
        try:
            command = self._build_command(script_path)
            command.append(action)
            if key_id is not None:
                command.append(key_id)
            if challenge_b64 is not None:
                command.append(challenge_b64)
            proc = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if not stdout:
                raise RuntimeError(stderr or "macOS Secure Enclave helper returned no output")
            payload = json.loads(stdout)
            if proc.returncode != 0 or not payload.get("ok"):
                raise RuntimeError(str(payload.get("error") or stderr or "macOS Secure Enclave helper failed"))
            return payload
        finally:
            script_path.unlink(missing_ok=True)

    def _ensure_compiled_helper(self) -> Path | None:
        if not self._swiftc:
            return None
        cache_dir = self._cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        helper_binary = cache_dir / f"mac-secure-enclave-helper-{self._helper_hash()}"
        if helper_binary.exists():
            return helper_binary

        source_path = cache_dir / f"{helper_binary.name}.swift"
        source_path.write_text(MACOS_SECURE_ENCLAVE_HELPER, encoding="utf8")
        try:
            compile_command = self._build_compile_command(source_path, helper_binary)
            proc = subprocess.run(
                compile_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                raise RuntimeError(stderr or "macOS Secure Enclave helper compilation failed")
            helper_binary.chmod(0o700)
            return helper_binary
        finally:
            source_path.unlink(missing_ok=True)

    def _cache_dir(self) -> Path:
        return Path.home() / "Library" / "Caches" / "unolock-agent-mcp"

    def _helper_hash(self) -> str:
        return hashlib.sha256(MACOS_SECURE_ENCLAVE_HELPER.encode("utf8")).hexdigest()[:12]

    def _build_command(self, script_path: Path) -> list[str]:
        if self._swift and Path(self._swift).name == "xcrun":
            return [self._swift, "swift", str(script_path)]
        if self._swift:
            return [self._swift, str(script_path)]
        raise RuntimeError("swift or xcrun is not available")

    def _build_compile_command(self, script_path: Path, output_path: Path) -> list[str]:
        if self._swiftc and Path(self._swiftc).name == "xcrun":
            return [self._swiftc, "swiftc", str(script_path), "-o", str(output_path)]
        if self._swiftc:
            return [self._swiftc, str(script_path), "-o", str(output_path)]
        raise RuntimeError("swiftc or xcrun is not available")

    def _binding_info_from_payload(self, payload: object) -> KeyBindingInfo:
        if not isinstance(payload, dict):
            raise TypeError("Invalid binding info payload from macOS Secure Enclave helper")
        return KeyBindingInfo(
            protection=str(payload.get("protection", "mac-secure-enclave")),
            exportable=bool(payload.get("exportable", False)),
            attestation_supported=bool(payload.get("attestation_supported", False)),
            device_binding=str(payload.get("device_binding", "hardware:secure-enclave")),
        )

    @staticmethod
    def _normalize_signature(signature: bytes) -> bytes:
        if len(signature) == 64:
            return signature
        r, s = decode_dss_signature(signature)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    @staticmethod
    def _diagnostic_summary_for_exception(exc: Exception) -> str:
        text = str(exc)
        if "-34018" in text:
            return "Secure Enclave key creation failed with OSStatus -34018."
        return "Secure Enclave helper could not create a signing key."

    @staticmethod
    def _diagnostic_advice_for_exception(exc: Exception) -> list[str]:
        text = str(exc)
        advice = [
            "Use a Secure Enclave-capable Mac and make sure the login keychain is available.",
            "Install Xcode command line tools if the Swift helper cannot run.",
        ]
        if "-34018" in text:
            advice = [
                "Run the MCP from a normal logged-in macOS user session, not a headless or restricted launch context.",
                "Make sure the login keychain is unlocked and available to the current process.",
                "Try launching the MCP from Terminal.app or another normal user shell first, then rerun tpm-diagnose.",
                "If a GUI MCP host is launching the MCP, make sure that host is allowed to access the user's login keychain.",
            ] + advice
        return advice

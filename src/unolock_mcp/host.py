from __future__ import annotations

import atexit
import inspect
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio

from unolock_mcp import __version__ as MCP_VERSION
from unolock_mcp.config import default_config_path
from unolock_mcp.mcp.server import create_mcp_server


class LocalHostError(RuntimeError):
    pass


SUPPORTED_MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_CAPABILITIES = {
    "experimental": {},
    "prompts": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "tools": {"listChanged": False},
}
DEFAULT_DAEMON_STATUS_TIMEOUT = 5.0
DEFAULT_DAEMON_START_TIMEOUT = 300.0
DEFAULT_DAEMON_STOP_TIMEOUT = 15.0
DEFAULT_DAEMON_LIST_TIMEOUT = 60.0
DEFAULT_DAEMON_CALL_TIMEOUT = 300.0
DAEMON_KEEPALIVE_POLL_SECONDS = 10.0


@dataclass
class LocalDaemonState:
    pid: int
    token: str
    version: str
    started_at: float
    port: int | None = None
    socket_path: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload = {
            "pid": self.pid,
            "token": self.token,
            "version": self.version,
            "started_at": self.started_at,
        }
        if self.port is not None:
            payload["port"] = self.port
        if self.socket_path:
            payload["socket_path"] = self.socket_path
        return payload

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "LocalDaemonState":
        return cls(
            pid=int(raw["pid"]),
            token=str(raw["token"]),
            version=str(raw.get("version") or MCP_VERSION),
            started_at=float(raw.get("started_at") or 0.0),
            port=int(raw["port"]) if raw.get("port") is not None else None,
            socket_path=str(raw["socket_path"]) if raw.get("socket_path") else None,
        )


def _state_dir() -> Path:
    return default_config_path().parent


def daemon_state_path() -> Path:
    return _state_dir() / "daemon.json"


def daemon_log_path() -> Path:
    return _state_dir() / "daemon.log"


def daemon_socket_path() -> Path:
    return _state_dir() / "daemon.sock"


def _supports_local_unix_socket() -> bool:
    return hasattr(socket, "AF_UNIX") and hasattr(socketserver, "UnixStreamServer")


def _chmod_if_supported(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    path.chmod(mode)


def _ensure_state_dir() -> None:
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_if_supported(state_dir, 0o700)


def _unlink_socket_file() -> None:
    socket_path = daemon_socket_path()
    if socket_path.exists() or socket_path.is_socket():
        socket_path.unlink()


def _write_daemon_state(state: LocalDaemonState) -> None:
    _ensure_state_dir()
    path = daemon_state_path()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state.to_json(), indent=2), encoding="utf8")
    _chmod_if_supported(temp_path, 0o600)
    temp_path.replace(path)
    _chmod_if_supported(path, 0o600)


def _clear_daemon_state() -> None:
    path = daemon_state_path()
    if path.exists():
        path.unlink()
    if _supports_local_unix_socket():
        _unlink_socket_file()


def load_daemon_state() -> LocalDaemonState | None:
    path = daemon_state_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf8"))
    except json.JSONDecodeError:
        _clear_daemon_state()
        return None
    if not isinstance(raw, dict):
        _clear_daemon_state()
        return None
    try:
        return LocalDaemonState.from_json(raw)
    except (KeyError, TypeError, ValueError):
        _clear_daemon_state()
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _request_daemon(
    state: LocalDaemonState,
    payload: dict[str, Any],
    timeout: float | None = DEFAULT_DAEMON_CALL_TIMEOUT,
) -> dict[str, Any]:
    request = dict(payload)
    request["token"] = state.token
    data = (json.dumps(request) + "\n").encode("utf8")
    if state.socket_path and _supports_local_unix_socket():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if timeout is not None:
            sock.settimeout(timeout)
        sock.connect(state.socket_path)
    else:
        if state.port is None:
            raise LocalHostError("Local UnoLock daemon state is missing a reachable transport.")
        sock = socket.create_connection(("127.0.0.1", state.port), timeout=timeout)
        if timeout is not None:
            sock.settimeout(timeout)
    with sock:
        sock.sendall(data)
        file_obj = sock.makefile("r", encoding="utf8")
        line = file_obj.readline()
    if not line:
        raise LocalHostError("Local UnoLock daemon closed the connection without replying.")
    response = json.loads(line)
    if not isinstance(response, dict):
        raise LocalHostError("Local UnoLock daemon returned an invalid response.")
    return response


def _status_shows_version_mismatch(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    return bool(status.get("running")) and str(status.get("version") or "") != MCP_VERSION


def get_daemon_status(timeout: float = DEFAULT_DAEMON_STATUS_TIMEOUT) -> dict[str, Any]:
    state = load_daemon_state()
    if state is None:
        return {"ok": True, "running": False}
    if not _pid_is_running(state.pid):
        _clear_daemon_state()
        return {"ok": True, "running": False}
    try:
        response = _request_daemon(state, {"command": "status"}, timeout=timeout)
    except (OSError, ValueError, json.JSONDecodeError, LocalHostError):
        if not _pid_is_running(state.pid):
            _clear_daemon_state()
            return {"ok": True, "running": False}
        return {
            "ok": False,
            "running": False,
            "reason": "daemon_unreachable",
            "message": (
                "UnoLock local daemon state exists but the daemon did not respond. On a fresh host, the first start "
                "can take longer because local cryptographic code may need to be compiled or prepared."
            ),
        }
    status = dict(response.get("result") or {})
    status["ok"] = bool(response.get("ok", True))
    status["running"] = True
    return status


class ToolHostController:
    def __init__(self) -> None:
        self._server = create_mcp_server()
        self._tools = self._server._tool_manager._tools
        self._started_at = time.time()
        self._keepalive_stop = threading.Event()
        self._keepalive_hook = getattr(self._server, "unolock_keepalive", None)
        self._keepalive_thread: threading.Thread | None = None
        if callable(self._keepalive_hook):
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop,
                name="unolock-daemon-keepalive",
                daemon=True,
            )
            self._keepalive_thread.start()

    def status_payload(self) -> dict[str, Any]:
        return {
            "pid": os.getpid(),
            "version": MCP_VERSION,
            "started_at": self._started_at,
            "tool_count": len(self._tools),
        }

    def close(self) -> None:
        self._keepalive_stop.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=0.5)

    def _run_keepalive_once(self) -> None:
        if callable(self._keepalive_hook):
            self._keepalive_hook()

    def _keepalive_loop(self) -> None:
        while not self._keepalive_stop.wait(DAEMON_KEEPALIVE_POLL_SECONDS):
            try:
                self._run_keepalive_once()
            except Exception:
                continue

    def list_tools(self) -> dict[str, Any]:
        return {
            "tools": sorted(self._tools.keys()),
        }

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        if tool_name not in self._tools:
            raise LocalHostError(f"Unknown UnoLock tool: {tool_name}")
        tool = self._tools[tool_name]
        kwargs = arguments or {}
        if not isinstance(kwargs, dict):
            raise LocalHostError("UnoLock tool arguments must be a JSON object.")
        signature = inspect.signature(tool.fn)
        bound = signature.bind_partial(**kwargs)
        return tool.fn(*bound.args, **bound.kwargs)

    def _run_async(self, fn, *args):
        async def runner():
            return await fn(*args)

        return anyio.run(runner)

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(value, list):
            return [ToolHostController._to_jsonable(item) for item in value]
        if isinstance(value, tuple):
            return [ToolHostController._to_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {
                key: ToolHostController._to_jsonable(item)
                for key, item in value.items()
            }
        return value

    def _initialize_result(self, requested_version: str | None) -> dict[str, Any]:
        protocol_version = requested_version or SUPPORTED_MCP_PROTOCOL_VERSION
        return {
            "protocolVersion": protocol_version,
            "capabilities": MCP_CAPABILITIES,
            "serverInfo": {
                "name": "UnoLock Agent",
                "version": MCP_VERSION,
            },
            "instructions": str(getattr(self._server, "instructions", "") or ""),
        }

    def _normalize_tool_result(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict) and ("content" in result or "structuredContent" in result):
            payload = dict(result)
            payload.setdefault("isError", False)
            return self._to_jsonable(payload)
        if isinstance(result, tuple) and len(result) == 2:
            content, structured = result
            return {
                "content": self._to_jsonable(list(content)),
                "structuredContent": self._to_jsonable(structured),
                "isError": False,
            }
        if isinstance(result, list):
            return {
                "content": self._to_jsonable(result),
                "isError": False,
            }
        if isinstance(result, dict):
            return {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "structuredContent": self._to_jsonable(result),
                "isError": False,
            }
        return {
            "content": [{"type": "text", "text": str(result)}],
            "isError": False,
        }

    def _jsonrpc_success(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": self._to_jsonable(result),
        }

    def _jsonrpc_error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def handle_mcp_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self._jsonrpc_error(None, -32600, "Request must be a JSON object.")
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params")
        if method == "notifications/initialized":
            return None
        if isinstance(method, str) and method.startswith("notifications/"):
            return None
        if not isinstance(method, str) or not method:
            return self._jsonrpc_error(request_id, -32600, "Missing JSON-RPC method.")
        if params is not None and not isinstance(params, dict):
            return self._jsonrpc_error(request_id, -32602, "MCP params must be a JSON object.")
        payload = params or {}
        try:
            if method == "initialize":
                return self._jsonrpc_success(request_id, self._initialize_result(payload.get("protocolVersion")))
            if method == "ping":
                return self._jsonrpc_success(request_id, {})
            if method == "tools/list":
                return self._jsonrpc_success(request_id, {"tools": self._run_async(self._server.list_tools)})
            if method == "tools/call":
                tool_name = payload.get("name")
                if not isinstance(tool_name, str) or not tool_name.strip():
                    return self._jsonrpc_error(request_id, -32602, "tools/call requires a tool name.")
                arguments = payload.get("arguments") or {}
                if not isinstance(arguments, dict):
                    return self._jsonrpc_error(request_id, -32602, "tools/call arguments must be a JSON object.")
                return self._jsonrpc_success(request_id, self._normalize_tool_result(self.call_tool(tool_name, arguments)))
            if method == "resources/list":
                return self._jsonrpc_success(request_id, {"resources": self._run_async(self._server.list_resources)})
            if method == "resources/templates/list":
                return self._jsonrpc_success(
                    request_id,
                    {"resourceTemplates": self._run_async(self._server.list_resource_templates)},
                )
            if method == "resources/read":
                uri = payload.get("uri")
                if not isinstance(uri, str) or not uri.strip():
                    return self._jsonrpc_error(request_id, -32602, "resources/read requires a resource URI.")
                return self._jsonrpc_success(request_id, {"contents": self._run_async(self._server.read_resource, uri)})
            if method == "prompts/list":
                return self._jsonrpc_success(request_id, {"prompts": self._run_async(self._server.list_prompts)})
            if method == "prompts/get":
                name = payload.get("name")
                if not isinstance(name, str) or not name.strip():
                    return self._jsonrpc_error(request_id, -32602, "prompts/get requires a prompt name.")
                arguments = payload.get("arguments") or None
                if arguments is not None and not isinstance(arguments, dict):
                    return self._jsonrpc_error(request_id, -32602, "prompts/get arguments must be a JSON object.")
                return self._jsonrpc_success(request_id, self._run_async(self._server.get_prompt, name, arguments))
            return self._jsonrpc_error(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            return self._jsonrpc_error(request_id, -32603, str(exc).strip() or exc.__class__.__name__)


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _ControlRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline()
        if not raw:
            return
        try:
            request = json.loads(raw.decode("utf8"))
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object.")
            if request.get("token") != self.server.auth_token:
                self._write({"ok": False, "reason": "unauthorized", "message": "Invalid daemon token."})
                return
            command = request.get("command")
            if command == "status":
                self._write({"ok": True, "result": self.server.controller.status_payload()})
                return
            if command == "list_tools":
                self._write({"ok": True, "result": self.server.controller.list_tools()})
                return
            if command == "call":
                tool_name = request.get("tool")
                if not isinstance(tool_name, str) or not tool_name.strip():
                    raise LocalHostError("Tool name is required.")
                result = self.server.controller.call_tool(tool_name, request.get("arguments"))
                self._write({"ok": True, "result": result})
                return
            if command == "rpc":
                response = self.server.controller.handle_mcp_request(request.get("message") or {})
                self._write({"ok": True, "has_response": response is not None, "response": response})
                return
            if command == "shutdown":
                self._write({"ok": True, "result": {"stopping": True}})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            raise LocalHostError(f"Unknown daemon command: {command}")
        except Exception as exc:
            self._write({
                "ok": False,
                "reason": "daemon_error",
                "message": str(exc).strip() or exc.__class__.__name__,
            })

    def _write(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload) + "\n").encode("utf8"))


def serve_local_daemon_forever() -> int:
    controller = ToolHostController()
    auth_token = secrets.token_urlsafe(32)
    _ensure_state_dir()

    if _supports_local_unix_socket():
        _unlink_socket_file()

        class _Server(_ThreadingUnixServer):
            pass

        server = _Server(str(daemon_socket_path()), _ControlRequestHandler)
        _chmod_if_supported(daemon_socket_path(), 0o600)
        transport = {"socket_path": str(daemon_socket_path()), "port": None}
    else:
        class _Server(_ThreadingTCPServer):
            pass

        server = _Server(("127.0.0.1", 0), _ControlRequestHandler)
        transport = {"socket_path": None, "port": int(server.server_address[1])}

    with server:
        server.controller = controller
        server.auth_token = auth_token
        state = LocalDaemonState(
            pid=os.getpid(),
            token=auth_token,
            version=MCP_VERSION,
            started_at=time.time(),
            port=transport["port"],
            socket_path=transport["socket_path"],
        )
        _write_daemon_state(state)
        atexit.register(_clear_daemon_state)
        try:
            server.serve_forever()
        finally:
            controller.close()
            _clear_daemon_state()
    return 0


def ensure_daemon_running(timeout: float = DEFAULT_DAEMON_START_TIMEOUT) -> dict[str, Any]:
    status = get_daemon_status()
    if status.get("running") and not _status_shows_version_mismatch(status):
        return status
    if _status_shows_version_mismatch(status):
        stopped = stop_daemon()
        if not stopped.get("ok") or stopped.get("running"):
            raise LocalHostError(
                "A stale UnoLock local daemon is still running after an upgrade. Stop it before retrying."
            )

    _ensure_state_dir()
    log_file = daemon_log_path().open("a", encoding="utf8")
    _chmod_if_supported(daemon_log_path(), 0o600)
    if getattr(sys, "frozen", False):
        argv = [sys.executable, "_daemon"]
    else:
        argv = [sys.executable, "-m", "unolock_mcp", "_daemon"]
    kwargs: dict[str, Any] = {
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
        "start_new_session": True,
    }
    if getattr(sys, "frozen", False):
        # Start the daemon as a fresh top-level PyInstaller process so it does
        # not depend on the parent's temporary extraction directory.
        kwargs["env"] = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    process = subprocess.Popen(argv, **kwargs)
    log_file.close()
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_daemon_status()
        if status.get("running"):
            return status
        if process.poll() is not None:
            raise LocalHostError(
                f"UnoLock local daemon exited during startup. On a fresh host, the first start can take longer "
                f"because local cryptographic code may need to be compiled or prepared. See {daemon_log_path()} "
                f"for details."
            )
        time.sleep(0.1)
    raise LocalHostError(
        f"UnoLock local daemon did not become ready within {timeout:.0f}s. On a fresh host, the first start can "
        f"take longer because local cryptographic code may need to be compiled or prepared. See "
        f"{daemon_log_path()} for details."
    )


def stop_daemon(timeout: float = DEFAULT_DAEMON_STOP_TIMEOUT) -> dict[str, Any]:
    state = load_daemon_state()
    if state is None:
        return {"ok": True, "running": False, "stopped": False}
    response = _request_daemon(state, {"command": "shutdown"}, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_daemon_status()
        if not status.get("running"):
            return {"ok": True, "running": False, "stopped": True}
        time.sleep(0.1)
    return {
        "ok": False,
        "running": True,
        "stopped": False,
        "reason": "shutdown_timeout",
        "message": "UnoLock local daemon did not stop within the timeout window.",
    }


def list_tools(auto_start: bool = True, timeout: float = DEFAULT_DAEMON_LIST_TIMEOUT) -> dict[str, Any]:
    state = load_daemon_state()
    status = get_daemon_status() if state is not None else {"running": False}
    if state is None or not status.get("running") or _status_shows_version_mismatch(status):
        if not auto_start:
            return {"ok": False, "reason": "daemon_not_running", "message": "UnoLock local daemon is not running."}
        ensure_daemon_running()
        state = load_daemon_state()
    if state is None:
        raise LocalHostError("UnoLock local daemon state is unavailable after startup.")
    return _request_daemon(state, {"command": "list_tools"}, timeout=timeout)


def call_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    auto_start: bool = True,
    timeout: float = DEFAULT_DAEMON_CALL_TIMEOUT,
) -> dict[str, Any]:
    state = load_daemon_state()
    status = get_daemon_status() if state is not None else {"running": False}
    if state is None or not status.get("running") or _status_shows_version_mismatch(status):
        if not auto_start:
            return {"ok": False, "reason": "daemon_not_running", "message": "UnoLock local daemon is not running."}
        ensure_daemon_running()
        state = load_daemon_state()
    if state is None:
        raise LocalHostError("UnoLock local daemon state is unavailable after startup.")
    return _request_daemon(
        state,
        {"command": "call", "tool": tool_name, "arguments": arguments or {}},
        timeout=timeout,
    )


def proxy_stdio_to_daemon(*, auto_start: bool = True, timeout: float | None = None) -> int:
    state = load_daemon_state()
    status = get_daemon_status() if state is not None else {"running": False}
    if state is None or not status.get("running") or _status_shows_version_mismatch(status):
        if not auto_start:
            raise LocalHostError("UnoLock local daemon is not running.")
        ensure_daemon_running()
        state = load_daemon_state()
    if state is None:
        raise LocalHostError("UnoLock local daemon state is unavailable after startup.")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {exc}",
                },
            }
            print(json.dumps(response), flush=True)
            continue
        daemon_response = _request_daemon(state, {"command": "rpc", "message": message}, timeout=timeout)
        if daemon_response.get("has_response") and daemon_response.get("response") is not None:
            print(json.dumps(daemon_response["response"]), flush=True)
    return 0

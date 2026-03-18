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

from unolock_mcp import __version__ as MCP_VERSION
from unolock_mcp.config import default_config_path
from unolock_mcp.mcp.server import create_mcp_server


class LocalHostError(RuntimeError):
    pass


@dataclass
class LocalDaemonState:
    pid: int
    port: int
    token: str
    version: str
    started_at: float

    def to_json(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "port": self.port,
            "token": self.token,
            "version": self.version,
            "started_at": self.started_at,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "LocalDaemonState":
        return cls(
            pid=int(raw["pid"]),
            port=int(raw["port"]),
            token=str(raw["token"]),
            version=str(raw.get("version") or MCP_VERSION),
            started_at=float(raw.get("started_at") or 0.0),
        )


def _state_dir() -> Path:
    return default_config_path().parent


def daemon_state_path() -> Path:
    return _state_dir() / "daemon.json"


def daemon_log_path() -> Path:
    return _state_dir() / "daemon.log"


def _ensure_state_dir() -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)


def _write_daemon_state(state: LocalDaemonState) -> None:
    _ensure_state_dir()
    path = daemon_state_path()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state.to_json(), indent=2), encoding="utf8")
    temp_path.replace(path)


def _clear_daemon_state() -> None:
    path = daemon_state_path()
    if path.exists():
        path.unlink()


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


def _request_daemon(state: LocalDaemonState, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    request = dict(payload)
    request["token"] = state.token
    data = (json.dumps(request) + "\n").encode("utf8")
    with socket.create_connection(("127.0.0.1", state.port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(data)
        file_obj = sock.makefile("r", encoding="utf8")
        line = file_obj.readline()
    if not line:
        raise LocalHostError("Local UnoLock daemon closed the connection without replying.")
    response = json.loads(line)
    if not isinstance(response, dict):
        raise LocalHostError("Local UnoLock daemon returned an invalid response.")
    return response


def get_daemon_status(timeout: float = 2.0) -> dict[str, Any]:
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
            "message": "UnoLock local daemon state exists but the daemon did not respond.",
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

    def status_payload(self) -> dict[str, Any]:
        return {
            "pid": os.getpid(),
            "version": MCP_VERSION,
            "started_at": self._started_at,
            "tool_count": len(self._tools),
        }

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


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
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

    class _Server(_ThreadingTCPServer):
        pass

    with _Server(("127.0.0.1", 0), _ControlRequestHandler) as server:
        server.controller = controller
        server.auth_token = auth_token
        state = LocalDaemonState(
            pid=os.getpid(),
            port=int(server.server_address[1]),
            token=auth_token,
            version=MCP_VERSION,
            started_at=time.time(),
        )
        _write_daemon_state(state)
        atexit.register(_clear_daemon_state)
        try:
            server.serve_forever()
        finally:
            _clear_daemon_state()
    return 0


def ensure_daemon_running(timeout: float = 15.0) -> dict[str, Any]:
    status = get_daemon_status()
    if status.get("running"):
        return status

    _ensure_state_dir()
    log_file = daemon_log_path().open("a", encoding="utf8")
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
                f"UnoLock local daemon exited during startup. See {daemon_log_path()} for details."
            )
        time.sleep(0.1)
    raise LocalHostError(
        f"UnoLock local daemon did not become ready within {timeout:.0f}s. See {daemon_log_path()} for details."
    )


def stop_daemon(timeout: float = 5.0) -> dict[str, Any]:
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


def list_tools(auto_start: bool = True, timeout: float = 5.0) -> dict[str, Any]:
    state = load_daemon_state()
    if state is None or not get_daemon_status().get("running"):
        if not auto_start:
            return {"ok": False, "reason": "daemon_not_running", "message": "UnoLock local daemon is not running."}
        ensure_daemon_running()
        state = load_daemon_state()
    if state is None:
        raise LocalHostError("UnoLock local daemon state is unavailable after startup.")
    return _request_daemon(state, {"command": "list_tools"}, timeout=timeout)


def call_tool(tool_name: str, arguments: dict[str, Any] | None = None, *, auto_start: bool = True, timeout: float = 30.0) -> dict[str, Any]:
    state = load_daemon_state()
    if state is None or not get_daemon_status().get("running"):
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

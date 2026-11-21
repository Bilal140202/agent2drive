#!/usr/bin/env python3
"""MCP stdio server for agent2drive.

Exposes the delivery workflow as MCP tools without ever returning tokens or
client secrets to the model. All core calls are wrapped so their print()
output becomes structured tool output instead of corrupting the stdio
JSON-RPC stream.

    pip install 'agent2drive[mcp]'
    agent2drive-mcp
"""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import agent2drive as a2d

try:  # MCP SDK v2
    from mcp.server.mcpserver import MCPServer
    _V2 = True
except ImportError:  # MCP SDK v1
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore
    _V2 = False

VERSION = "0.4.0"


class A2DResult(BaseModel):
    """Structured result schema for MCP v2; instances stay dicts at runtime."""

    ok: bool
    code: str
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


mcp = MCPServer(
    name="agent2drive",
    version=VERSION,
    instructions=(
        "Deliver files into the user's Google Drive for review. "
        "OAuth is user-mediated: a2d_consent_url gives a link the user must "
        "open; only after they paste the redirect URL may a2d_connect be "
        "called. Uploads verify size, MD5 and SHA-1. Never overwrite a file "
        "without an explicit confirm='REPLACE'."),
)


# ------------------------------------------------------------- helpers
def tool(name, description):
    """Register a tool with structured output where the SDK supports it."""
    kwargs = {"name": name, "description": description}
    if _V2:
        kwargs["structured_output"] = True
    return mcp.tool(**kwargs)


def _result(ok, code, message="", data=None):
    return {"ok": bool(ok), "code": code, "message": message,
            "data": data if data is not None else {}}


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _call(fn, *args, code="call", **kwargs):
    """Run a core function, capturing its stdout for the tool response."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            value = fn(*args, **kwargs)
    except SystemExit as e:
        return _result(False, f"{code}_error", str(e), {"log": buf.getvalue()})
    except Exception as e:  # noqa: BLE001 - report, never leak a traceback
        return _result(False, f"{code}_error",
                       f"{type(e).__name__}: {e}", {"log": buf.getvalue()})
    return _result(True, code, buf.getvalue().strip() or "ok",
                   {"result": _jsonable(value), "log": buf.getvalue()})


def _allowed_roots():
    raw = os.environ.get("A2D_ALLOWED_ROOTS", "")
    roots = [Path(p).expanduser().resolve() for p in raw.split(os.pathsep)
             if p.strip()]
    return roots or [Path.cwd().resolve()]


def _is_allowed(path):
    """Resolve symlinks so a link can't escape an allowed directory."""
    target = Path(path).expanduser().resolve()
    return any(target == root or root in target.parents
               for root in _allowed_roots())


def _build_consent_url():
    client_id, _ = a2d.load_client()
    return a2d.consent_url(client_id, a2d.new_oauth_state())


def _read(slot, kind):
    buf = io.StringIO()
    with redirect_stdout(buf):
        text = (a2d._read_manifest(slot) if kind == "manifest"
                else a2d.cmd_ls(slot) or "")
        lines = buf.getvalue().strip().splitlines()
    return (text or "\n".join(lines)).strip()


# ----------------------------------------------------------------- tools
@tool(name="a2d_status", description="Check the live Google Drive connection.")
def a2d_status() -> A2DResult:
    result = _call(a2d.status, quiet=True, code="status")
    result["ok"] = result["data"].get("result") == "AUTH_OK"
    return result


@tool(name="a2d_set_client",
          description="Store your own Google OAuth client id and secret (secret is never returned).")
def a2d_set_client(client_id: str, client_secret: str) -> A2DResult:
    if not client_id or not client_secret:
        return _result(False, "validation_error", "client_id and client_secret are required")
    result = _call(a2d.set_client, client_id, client_secret, code="client")
    result["message"] = "OAuth client stored (secret redacted)"
    return result


@tool(name="a2d_consent_url",
          description="Print the Google consent URL the user must open; stores a one-time state nonce.")
def a2d_consent_url() -> A2DResult:
    return _call(_build_consent_url, code="consent_url")


@tool(name="a2d_connect",
          description="Exchange the user's pasted redirect URL for a Drive token. Do this immediately.")
def a2d_connect(pasted_url: str) -> A2DResult:
    if not pasted_url or not pasted_url.strip():
        return _result(False, "validation_error", "pasted_url is required")
    return _call(a2d.exchange, pasted_url.strip(), code="connect")


@tool(name="a2d_init_slot",
          description="Create a Drive slot root and its MANIFEST.md.")
def a2d_init_slot(slot: str) -> A2DResult:
    return _call(a2d.cmd_init, slot, code="init_slot")


@tool(name="a2d_upload",
          description="Upload and verify a file into a slot; writes a manifest row. Overwrites require confirm='REPLACE'.")
def a2d_upload(slot: str, path: str, folder: str | None = None,
               replace: bool = False, confirm: str | None = None) -> A2DResult:
    if not _is_allowed(path):
        return _result(False, "path_denied",
                       "path is outside A2D_ALLOWED_ROOTS",
                       {"allowed_roots": [str(p) for p in _allowed_roots()]})
    if replace and confirm != "REPLACE":
        return _result(False, "confirmation_required",
                       "overwriting needs confirm='REPLACE'")
    return _call(a2d.cmd_upload, slot, path, folder, replace, code="upload")


@tool(name="a2d_list", description="List all files in a Drive slot.")
def a2d_list(slot: str) -> A2DResult:
    result = _call(a2d.cmd_ls, slot, code="list")
    result["message"] = _read(slot, "list") or result["message"]
    return result


@tool(name="a2d_manifest", description="Read a slot's delivery manifest / audit trail.")
def a2d_manifest(slot: str) -> A2DResult:
    result = _call(a2d.cmd_manifest, slot, code="manifest")
    result["message"] = _read(slot, "manifest") or result["message"]
    return result


# ------------------------------------------------------------- resources
@mcp.resource("a2d://config")
def config_resource() -> str:
    """Non-secret configuration of this server."""
    return json.dumps({
        "version": VERSION,
        "drive_root": a2d.ROOT,
        "state_home": str(a2d.HOME),
        "allowed_roots": [str(p) for p in _allowed_roots()],
    }, indent=2)


@mcp.resource("a2d://slot/{slot}/manifest")
def manifest_resource(slot: str) -> str:
    """Delivery manifest for a slot."""
    return _read(slot, "manifest")


# --------------------------------------------------------------- prompts
@mcp.prompt(name="deliver-file",
            description="Deliver a created file to the review canvas.")
def deliver_file_prompt(slot: str) -> str:
    return (
        f"Deliver the file you just created into Drive slot '{slot}'. "
        "1) call a2d_upload with the absolute path and a short folder name "
        "(e.g. 'drafts' or 'final'); 2) if it reports SIZE-ONLY, tell the user; "
        "3) if a file with that name already exists, ask before passing "
        "replace=True and confirm='REPLACE'; 4) report the verified result "
        "and where to review it (Google Drive -> AgentDeliveries/"
        f"{slot}/).")


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

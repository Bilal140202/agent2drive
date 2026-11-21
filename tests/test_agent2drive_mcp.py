"""Tests for the MCP stdio server adapter (no live Drive calls)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent2drive_mcp as srv  # noqa: E402
import agent2drive as a2d  # noqa: E402


def test_tools_are_registered():
    names = [t.name for t in srv.mcp._tool_manager.list_tools()]
    assert {"a2d_status", "a2d_connect", "a2d_upload", "a2d_manifest"} \
        <= set(names)


def test_call_captures_stdout_and_systemexit():
    def noisy():
        print("verified: OK")
        return 0

    result = srv._call(noisy, code="upload")
    assert result["ok"] is True
    assert "verified: OK" in result["message"]
    assert result["data"]["result"] == 0

    def failing():
        raise SystemExit("nope")

    result = srv._call(failing, code="upload")
    assert result["ok"] is False
    assert result["code"] == "upload_error"
    assert "nope" in result["message"]


def test_allowed_roots_resolve_symlinks(monkeypatch, tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    f = inside / "file.txt"
    f.write_text("x")
    outside = tmp_path.parent / "outside-mcp-test.txt"
    outside.write_text("x")
    monkeypatch.setenv("A2D_ALLOWED_ROOTS", str(inside))

    assert srv._is_allowed(f) is True
    assert srv._is_allowed(outside) is False

    link = inside / "escape"
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
        assert srv._is_allowed(link / "outside-mcp-test.txt") is False
    except OSError:
        pass


def test_upload_rejects_path_outside_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("A2D_ALLOWED_ROOTS", str(tmp_path))
    outside = tmp_path.parent / "outside-upload-test.txt"
    outside.write_text("x")
    result = srv.a2d_upload("canvas", str(outside))
    assert result["ok"] is False
    assert result["code"] == "path_denied"


def test_upload_requires_explicit_replace_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("A2D_ALLOWED_ROOTS", str(tmp_path))
    f = tmp_path / "a.txt"
    f.write_text("x")
    result = srv.a2d_upload("canvas", str(f), replace=True)
    assert result["code"] == "confirmation_required"
    assert result["ok"] is False


def test_upload_returns_verification_log(monkeypatch, tmp_path):
    monkeypatch.setenv("A2D_ALLOWED_ROOTS", str(tmp_path))
    f = tmp_path / "a.txt"
    f.write_text("x")

    def fake_upload(slot, path, folder=None, replace=False):
        print("[agent2drive] verified: size True · md5 True · sha1 True -> OK")
        return 0

    monkeypatch.setattr(a2d, "cmd_upload", fake_upload)
    result = srv.a2d_upload("canvas", str(f), folder="drafts")
    assert result["ok"] is True
    assert "verified: size True" in result["message"]


def test_set_client_never_echoes_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(a2d, "STATE", tmp_path)
    monkeypatch.setattr(a2d, "CLIENT", tmp_path / "client.json")
    secret = "super-secret-value-123456789"
    result = srv.a2d_set_client("id.apps.googleusercontent.com", secret)
    assert result["ok"] is True
    assert secret not in json.dumps(result)
    assert secret in (tmp_path / "client.json").read_text()


def test_config_resource_has_no_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("A2D_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.delenv("A2D_HOME", raising=False)
    data = json.loads(srv.config_resource())
    assert data["version"] == "0.4.0"
    assert data["drive_root"] == "AgentDeliveries"
    assert str(tmp_path) in data["allowed_roots"]

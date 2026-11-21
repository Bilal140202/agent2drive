"""Tests for agent2drive: pure logic plus injected-rclone failure paths."""
import base64
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent2drive as a2d  # noqa: E402


# ------------------------------------------------------------- pure logic
def test_reveal_roundtrip_with_rclone_known_value():
    from cryptography.hazmat.primitives.ciphers import (Cipher, algorithms,
                                                         modes)
    iv = bytes(range(16))
    enc = Cipher(algorithms.AES(a2d.AES_KEY), modes.CTR(iv)).encryptor()
    payload = b"round-trip-reveal-test-payload"
    ct = iv + bytes(enc.update(payload) + enc.finalize())
    obscured = base64.urlsafe_b64encode(ct).decode().rstrip("=")
    assert a2d.reveal(obscured) == payload.decode()


def test_reveal_rejects_garbage():
    assert a2d.reveal("") is None
    assert a2d.reveal("not base64 !!!") is None
    assert a2d.reveal("abcde") is None


def test_parse_code_from_pasted_redirect_url():
    url = "http://127.0.0.1:53682/?state=xyz&code=4%2F0ABC_def-123"
    assert a2d.parse_code(url) == "4/0ABC_def-123"


def test_parse_code_accepts_bare_code_and_quotes():
    assert a2d.parse_code("4/0XYZ") == "4/0XYZ"
    assert a2d.parse_code("'4/0XYZ'\n") == "4/0XYZ"


def test_parse_code_empty_is_loud():
    with pytest.raises(SystemExit):
        a2d.parse_code("")


def test_consent_url_has_required_params_and_no_openid():
    url = a2d.consent_url("test-client-id.apps.googleusercontent.com", "nonce")
    assert "client_id=test-client-id" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A53682%2F" in url
    assert "drive.file" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=nonce" in url
    assert "openid" not in url


@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "linux-amd64"),
    ("Linux", "aarch64", "linux-arm64"),
    ("Darwin", "arm64", "osx-arm64"),
    ("Windows", "AMD64", "windows-amd64"),
])
def test_platform_suffix(monkeypatch, system, machine, expected):
    monkeypatch.setattr(a2d.platform, "system", lambda: system)
    monkeypatch.setattr(a2d.platform, "machine", lambda: machine)
    assert a2d.platform_suffix() == expected


def test_rclone_zip_url_env_override(monkeypatch):
    monkeypatch.setenv("RCLONE_ZIP", "https://example.test/rclone.zip")
    assert a2d.rclone_zip_url() == "https://example.test/rclone.zip"


def test_slots_are_validated():
    assert a2d._check_slot("canvas") == "canvas"
    for bad in ("", "..", "../escape", "a/b", "A/B", "a b", "-lead"):
        with pytest.raises(SystemExit):
            a2d._check_slot(bad)


def test_folders_are_user_defined_but_constrained():
    assert a2d._check_folder(None) is None
    assert a2d._check_folder("final") == "final"
    assert a2d._check_folder("2026-11") == "2026-11"
    assert a2d._check_folder("raw audio") == "raw audio"
    for bad in ("../escape", "a/b", "a\\b", "..", ".", "", " x", "x "):
        with pytest.raises(SystemExit):
            a2d._check_folder(bad)


def test_local_hashes(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    md5, sha1 = a2d._local_hashes(f)
    assert md5 == "900150983cd24fb0d6963f7d28e17f72"
    assert sha1 == "a9993e364706816aba3e25717850c26c9cd0d89d"


# --------------------------------------------------------- OAuth state
def test_oauth_state_roundtrip_and_replay(monkeypatch, tmp_path):
    monkeypatch.setattr(a2d, "OAUTH_STATE", tmp_path / "state.json")
    state = a2d.new_oauth_state()
    assert a2d.check_oauth_state(f"http://x/?state={state}&code=4/abc")
    with pytest.raises(SystemExit):
        a2d.check_oauth_state(f"http://x/?state={state}&code=4/abc")


def test_oauth_state_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(a2d, "OAUTH_STATE", tmp_path / "state.json")
    state = a2d.new_oauth_state()
    p = a2d.OAUTH_STATE
    d = json.loads(p.read_text())
    d["ts"] = time.time() - a2d.STATE_TTL - 1
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit):
        a2d.check_oauth_state(f"http://x/?state={state}&code=4/abc")


# -------------------------------------------------------- injected rclone
class FakeRclone:
    """Stand-in for _rc: in-memory remote with controllable hashes."""

    def __init__(self, src, *, hash_mode="good", existing=False):
        self.src = Path(src)
        self.hash_mode = hash_mode
        self.existing = existing
        self.calls = []
        self.remote = {}
        self.manifest = None
        self.md5, self.sha1 = a2d._local_hashes(self.src)

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "lsjson":
            files = []
            if self.existing or self.remote:
                files.append({"Name": self.src.name, "Size": self.src.stat().st_size})
            return type("P", (), {"returncode": 0,
                                  "stdout": json.dumps(files)})()
        if cmd == "copyto":
            self.remote[self.src.name] = self.src.stat().st_size
            return type("P", (), {"returncode": 0, "stdout": ""})()
        if cmd == "hashsum":
            algo = args[1]
            value = self.md5 if algo == "MD5" else self.sha1
            if self.hash_mode == "missing":
                return type("P", (), {"returncode": 1, "stdout": ""})()
            if self.hash_mode == "bad" and algo == "MD5":
                value = "0" * 32
            return type("P", (), {"returncode": 0,
                                  "stdout": f"{value}  {self.src.name}\n"})()
        if cmd == "deletefile":
            self.remote.pop(self.src.name, None)
            return type("P", (), {"returncode": 0, "stdout": ""})()
        if cmd == "cat":
            text = self.manifest or a2d._manifest_header("canvas")
            return type("P", (), {"returncode": 0, "stdout": text})()
        if cmd == "rcat":
            self.manifest = kwargs.get("stdin_data", "")
            return type("P", (), {"returncode": 0, "stdout": ""})()
        raise AssertionError(f"unexpected rclone call: {args}")


@pytest.fixture
def sample(tmp_path):
    f = tmp_path / "deliverable.txt"
    f.write_bytes(b"review me")
    return f


def test_upload_verifies_and_updates_manifest(monkeypatch, sample):
    fake = FakeRclone(sample)
    monkeypatch.setattr(a2d, "_rc", fake)
    assert a2d.cmd_upload("canvas", str(sample)) == 0
    assert fake.remote
    assert "| OK |" in fake.manifest
    assert sample.name in fake.manifest
    assert any(c[0] == "hashsum" for c in fake.calls)


def test_upload_refuses_collision_without_replace(monkeypatch, sample):
    fake = FakeRclone(sample, existing=True)
    monkeypatch.setattr(a2d, "_rc", fake)
    with pytest.raises(SystemExit, match="already exists"):
        a2d.cmd_upload("canvas", str(sample))
    assert not fake.remote


def test_upload_replace_overwrites(monkeypatch, sample):
    fake = FakeRclone(sample, existing=True)
    monkeypatch.setattr(a2d, "_rc", fake)
    assert a2d.cmd_upload("canvas", str(sample), replace=True) == 0
    assert any(c[0] == "copyto" for c in fake.calls)


def test_upload_hash_mismatch_deletes_remote_and_fails(monkeypatch, sample):
    fake = FakeRclone(sample, hash_mode="bad")
    monkeypatch.setattr(a2d, "_rc", fake)
    with pytest.raises(SystemExit, match="verification FAILED"):
        a2d.cmd_upload("canvas", str(sample))
    assert not fake.remote
    assert any(c[0] == "deletefile" for c in fake.calls)


def test_upload_without_remote_hashes_is_size_only(monkeypatch, sample):
    fake = FakeRclone(sample, hash_mode="missing")
    monkeypatch.setattr(a2d, "_rc", fake)
    assert a2d.cmd_upload("canvas", str(sample)) == 1
    assert "| SIZE-ONLY |" in fake.manifest


def test_rc_retries_then_succeeds(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        if len(calls) < 3:
            raise OSError("transient")
        return type("P", (), {"returncode": 0, "stdout": "ok",
                              "stderr": ""})()

    monkeypatch.setattr(a2d, "_ensure_rclone", lambda: None)
    monkeypatch.setattr(a2d.subprocess, "run", fake_run)
    monkeypatch.setattr(a2d.time, "sleep", lambda n: None)
    assert a2d._rc("about", "gdrive:", retries=2).stdout == "ok"
    assert len(calls) == 3


def test_connect_keeps_credentials_when_verification_breaks(monkeypatch, tmp_path):
    """The bug that produced a traceback after a successful exchange."""
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"access_token": "a", "token_type": "Bearer",
                               "refresh_token": "r", "expires_in": 3600}).encode()

    monkeypatch.setattr(a2d, "STATE", tmp_path)
    monkeypatch.setattr(a2d, "CONF", tmp_path / "rclone.conf")
    monkeypatch.setattr(a2d, "check_oauth_state", lambda pasted: True)
    monkeypatch.setattr(a2d, "load_client", lambda: ("id", "secret"))
    monkeypatch.setattr(a2d.urllib.request, "urlopen", lambda req, timeout: Resp())

    def boom(*a, **k):
        raise OSError("Exec format error")

    monkeypatch.setattr(a2d, "_rc", boom)
    assert a2d.exchange("4/abc") == "SAVED_UNVERIFIED"
    conf = (tmp_path / "rclone.conf").read_text()
    assert "refresh_token" in conf
    assert oct(conf and (tmp_path / "rclone.conf").stat().st_mode & 0o777) == "0o600"

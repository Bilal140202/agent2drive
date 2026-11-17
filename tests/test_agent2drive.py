"""Unit tests for agent2drive's pure functions (no network, no Drive)."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent2drive as a2d  # noqa: E402


def test_reveal_roundtrip_with_rclone_known_value():
    """Reveal a value obscured by rclone itself during CI prep is not
    possible offline, so verify the algorithm against a fixed
    (obscured -> plaintext) pair generated with the same algorithm."""
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
    assert a2d.reveal("abcde") is None  # len % 4 == 1


def test_parse_code_from_pasted_redirect_url():
    url = ("http://127.0.0.1:53682/?state=xyz&code=4/0ABC_def-123")
    assert a2d.parse_code(url) == "4/0ABC_def-123"


def test_parse_code_accepts_bare_code():
    assert a2d.parse_code("4/0XYZ") == "4/0XYZ"


def test_parse_code_empty_is_loud():
    with pytest.raises(SystemExit):
        a2d.parse_code("")


def test_consent_url_has_required_params():
    url = a2d.consent_url("test-client-id.apps.googleusercontent.com")
    assert "client_id=test-client-id" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A53682%2F" in url
    assert "drive.file" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_categories_and_root():
    assert a2d.CATEGORIES == ("master", "shorts", "subtitles",
                              "thumbnails", "assets", "backups")
    assert a2d.ROOT  # default AgentDeliveries unless env overrides

#!/usr/bin/env python3
"""agent2drive — one command to connect an agent to the user's Google
Drive, and one command per upload afterwards.

    python3 agent2drive.py                 # status (prints the connect
                                           # recipe when not connected)
    python3 agent2drive.py url             # print the consent URL
    python3 agent2drive.py connect '<PASTED_URL_OR_CODE>'
    python3 agent2drive.py init <slot>
    python3 agent2drive.py upload <slot> <file> [folder]
    python3 agent2drive.py ls <slot>

Self-restoring: a missing rclone binary is re-downloaded, and the OAuth
client (rclone's published default) is re-derived from the binary and
validated against Google's token endpoint. Only the refresh token
(state/rclone/rclone.conf, chmod 600) is irreplaceable — losing it just
means one fresh consent click; nothing on Drive is affected.

Scope is drive.file (least privilege): the agent can only see and manage
files it created itself. Tokens are never printed.
"""
import base64
import binascii
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "state/rclone"
CONF = STATE / "rclone.conf"
CLIENT = STATE / "client.json"
BIN = BASE / "bin/rclone"
STAGING = BASE / ".tmp/rclone-selfrestore"
ROOT = os.environ.get("GDRIVE_ROOT", "AgentDeliveries")

RCLONE_ZIP = ("https://downloads.rclone.org/"
              "rclone-current-linux-amd64.zip")
REDIRECT = "http://127.0.0.1:53682/"
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# rclone's published default OAuth client (open source,
# backend/drive/drive.go): the client id and the prefix of the secret's
# stored form. These are public constants, not secrets. Heavy users
# should configure their own client:
# https://rclone.org/drive/#making-your-own-client-id
CID_PREFIX = "202264815644-"
OBS_PREFIX = "eX8GpZTV"
AES_KEY = bytes([
    0x9c, 0x93, 0x5b, 0x48, 0x73, 0x0a, 0x55, 0x4d,
    0x6b, 0xfd, 0x7c, 0x63, 0xc8, 0x86, 0xa9, 0x2b,
    0xd3, 0x90, 0x19, 0x8e, 0xb8, 0x12, 0x8a, 0xfb,
    0xf4, 0xde, 0x16, 0x2b, 0x8b, 0x95, 0xf6, 0x38,
])


# ---------------------------------------------------------------- restore
def _ensure_rclone():
    if BIN.exists():
        return BIN
    print("[agent2drive] rclone missing (fresh sandbox?) - restoring…")
    STAGING.mkdir(parents=True, exist_ok=True)
    zip_path = STAGING / "rclone.zip"
    req = urllib.request.Request(
        RCLONE_ZIP, headers={"User-Agent": "agent2drive/0.2.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        zip_path.write_bytes(r.read())
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.endswith("/rclone"))
        z.extract(member, STAGING / "extracted")
    target = next((STAGING / "extracted").rglob("rclone"))
    BIN.parent.mkdir(parents=True, exist_ok=True)
    target.replace(BIN)
    BIN.chmod(0o755)
    print(f"[agent2drive] restored {BIN}")


def _rc(*args, timeout=900, check=True, stdin_data=None):
    _ensure_rclone()
    p = subprocess.run([str(BIN), "--config", str(CONF), *args],
                       capture_output=True, text=True, timeout=timeout,
                       input=stdin_data)
    if check and p.returncode != 0:
        raise RuntimeError(f"rclone {' '.join(args[:2])} failed: "
                           f"{p.stderr.strip()[-400:]}")
    return p


# ------------------------------------------------------- OAuth client
def reveal(obscured):
    """Reverse rclone's 'obscure' encoding (AES-256-CTR, base64url).

    Documented public algorithm: rclone fs/config/obscure/obscure.go.
    The IV is the first 16 bytes; CTR encryption == decryption."""
    if len(obscured) % 4 == 1:
        return None
    try:
        raw = base64.urlsafe_b64decode(obscured + "=" * (-len(obscured) % 4))
    except (ValueError, binascii.Error):
        return None
    if not 16 <= len(raw) <= 120:
        return None
    from cryptography.hazmat.primitives.ciphers import (  # noqa: PLC0415
        Cipher, algorithms, modes)
    enc = Cipher(algorithms.AES(AES_KEY), modes.CTR(raw[:16])).encryptor()
    out = bytes(enc.update(raw[16:]) + enc.finalize())
    try:
        return out.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None


def _binary_strings():
    _ensure_rclone()
    return subprocess.run(["strings", "-a", str(BIN)],
                          capture_output=True, text=True).stdout


def _client_secret_from_binary(client_id):
    """Derive the drive backend's default client secret from the binary.

    The secret is stored obscure-encoded among MANY other backend
    defaults, with no distinguishable prefix in current builds. So:
    reveal every plausible base64url token (with right-trims, because
    Go rodata merges adjacent literals), keep printable plaintexts, and
    let Google's token endpoint validate each — a wrong secret answers
    invalid_client, the right one answers invalid_grant for a fake
    code. No secret is ever printed."""
    out = _binary_strings()
    lines = out.splitlines()
    cid_re = re.compile(r"[0-9A-Za-z_\-]{20,}\.apps\.googleusercontent\.com")
    cid_idx = [i for i, s in enumerate(lines) if cid_re.search(s)]
    if cid_idx:
        client_id = cid_re.search(lines[cid_idx[0]]).group(0)
    tok_re = re.compile(r"[A-Za-z0-9_\-]{40,}")
    budget = 300_000
    seen, cands = set(), []
    for s in lines:
        for tok in tok_re.findall(s):
            for end in range(len(tok), 39, -1):
                if budget <= 0:
                    break
                budget -= 1
                pt = reveal(tok[:end])
                if (pt and 20 <= len(pt) <= 60 and pt.isprintable()
                        and " " not in pt and pt not in seen):
                    seen.add(pt)
                    cands.append(pt)
    cands.sort(key=len)  # real Google secrets are short; try those first
    for cand in cands:
        if _google_accepts_client(client_id, cand):
            return cand
    raise SystemExit("[agent2drive] could not derive the OAuth client "
                     "secret from the rclone binary")


def _google_accepts_client(client_id, secret):
    data = urllib.parse.urlencode({
        "code": "4/0INVALID-on-purpose", "client_id": client_id,
        "client_secret": secret, "redirect_uri": REDIRECT,
        "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
    except Exception:
        return False
    return "invalid_grant" in body  # client auth passed, code rejected


def load_client():
    if CLIENT.exists():
        d = json.loads(CLIENT.read_text())
        return d["client_id"], d["client_secret"]
    out = _binary_strings()
    cid_re = re.compile(r"[0-9A-Za-z_\-]{20,}\.apps\.googleusercontent\.com")
    m = cid_re.search(out)
    if not m:
        raise SystemExit("[agent2drive] client id not found in binary")
    client_id = m.group(0)
    print(f"[agent2drive] deriving OAuth client (rclone default, {client_id[:24]}…)")
    secret = _client_secret_from_binary(client_id)
    STATE.mkdir(parents=True, exist_ok=True)
    CLIENT.write_text(json.dumps({"client_id": client_id,
                                  "client_secret": secret}))
    CLIENT.chmod(0o600)
    return client_id, secret


# ------------------------------------------------------------ OAuth flow
def consent_url(client_id):
    state = urllib.parse.quote(json.dumps({"r": "agent2drive"}))
    return "https://accounts.google.com/o/oauth2/v2/auth?" + \
        urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": REDIRECT,
            "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
            "openid": "email"})


def parse_code(pasted):
    m = re.search(r"code=([A-Za-z0-9_\-.%/]+)", pasted or "")
    code = urllib.parse.unquote(m.group(1) if m else (pasted or "").strip())
    if not code:
        raise SystemExit("[agent2drive] no code found in the pasted text")
    return code


def exchange(pasted):
    """Single-use OAuth code -> refresh token -> rclone.conf (chmod 600).
    Do this FIRST when the user pastes: codes expire in ~10 minutes."""
    client_id, client_secret = load_client()
    data = urllib.parse.urlencode({
        "code": parse_code(pasted), "client_id": client_id,
        "client_secret": client_secret, "redirect_uri": REDIRECT,
        "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            tok = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[agent2drive] token exchange failed: "
                         f"{e.code} {e.read().decode()[:300]}") from None
    if "refresh_token" not in tok:
        raise SystemExit("[agent2drive] no refresh_token — the consent URL "
                         "must include prompt=consent; re-run `url`")
    tok["expiry"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() +
                                          tok.get("expires_in", 3600)))
    token_json = json.dumps({k: tok[k] for k in
                             ("access_token", "token_type",
                              "refresh_token", "expiry") if k in tok})
    STATE.mkdir(parents=True, exist_ok=True)
    CONF.write_text(f"[gdrive]\ntype = drive\nscope = drive.file\n"
                    f"client_id = {client_id}\n"
                    f"client_secret = {client_secret}\n"
                    f"token = {token_json}\n")
    CONF.chmod(0o600)
    print("[agent2drive] CONF_WRITTEN (chmod 600)")
    return status()


# ----------------------------------------------------------------- cmds
def status():
    if not CONF.exists():
        return "AUTH_MISSING"
    try:
        line = (_rc("about", "gdrive:", timeout=120).stdout.strip()
                .splitlines() or [""])[-1]
        print(f"AUTH_OK — {line.strip()}")
        return "AUTH_OK"
    except RuntimeError:
        return "AUTH_MISSING"


def cmd_init(slot):
    _rc("mkdir", f"gdrive:{ROOT}/{slot}")
    _rc("rcat", f"gdrive:{ROOT}/{slot}/MANIFEST.md", stdin_data=(
        f"# {slot}\n\nSlot created by agent2drive (root={ROOT}).\n"
        "No folder structure is imposed — folders exist only when you\n"
        "name one: upload <slot> <file> [folder], any folder you need.\n"))
    print(f"[agent2drive] slot ready: gdrive:{ROOT}/{slot}/")


def _check_folder(folder):
    """agent2drive never imposes structure; any single path component
    the user names is valid."""
    if folder is None:
        return None
    if (not folder or folder in (".", "..") or "/" in folder
            or "\\" in folder or folder.strip() != folder):
        raise SystemExit(f"[agent2drive] invalid folder name: {folder!r} "
                         "(one path component; no /, \\, '..', "
                         "surrounding spaces)")
    return folder


def cmd_upload(slot, path, folder=None):
    folder = _check_folder(folder)
    src = Path(path)
    if not src.is_file():
        raise SystemExit(f"[agent2drive] not a file: {src}")
    where = f"{slot}/{folder}" if folder else slot
    remote = f"gdrive:{ROOT}/{where}/{src.name}"
    print(f"[agent2drive] uploading {src.name} ({src.stat().st_size} B) "
          f"-> {remote}")
    _rc("copyto", str(src), remote)
    items = json.loads(_rc("lsjson", "--files-only", "--recursive",
                           f"gdrive:{ROOT}/{where}",
                           timeout=300).stdout)
    rsize = next((i["Size"] for i in items if i["Name"] == src.name), None)
    ok = rsize == src.stat().st_size
    print(f"[agent2drive] size verify: local={src.stat().st_size} "
          f"remote={rsize} -> {'OK' if ok else 'MISMATCH'}")
    return 0 if ok else 1


def cmd_ls(slot):
    p = _rc("lsf", "-R", "--files-only", f"gdrive:{ROOT}/{slot}/",
            timeout=300)
    print(p.stdout or "(empty)")


def main(argv):
    if not argv:
        if status() == "AUTH_OK":
            return 0
        print("AUTH_MISSING — one-time connect:")
        print(f"  1. python3 {Path(__file__).name} url        "
              f"-> give the user the printed URL")
        print("  2. user: open URL -> Allow -> browser fails on "
              "127.0.0.1:53682 (EXPECTED) -> copy the full address-bar URL")
        print(f"  3. python3 {Path(__file__).name} connect '<PASTED_URL>'")
        return 2
    cmd, *rest = argv
    if cmd == "status":
        return 0 if status() == "AUTH_OK" else 2
    if cmd == "url":
        print(consent_url(load_client()[0]))
        return 0
    if cmd == "connect" and rest:
        exchange(rest[0])
        return 0
    if cmd == "init" and rest:
        cmd_init(rest[0])
        return 0
    if cmd == "upload" and len(rest) >= 2:
        return cmd_upload(rest[0], rest[1],
                          rest[2] if len(rest) > 2 else None)
    if cmd == "ls" and rest:
        cmd_ls(rest[0])
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

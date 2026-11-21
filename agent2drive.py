#!/usr/bin/env python3
"""agent2drive — connect an agent to the user's Google Drive, and upload
reviewable deliverables one command at a time.

    agent2drive                         # status / connect recipe
    agent2drive status
    agent2drive url                     # print the consent URL
    agent2drive client [ID] [SECRET]    # use your own OAuth client (recommended)
    agent2drive connect [PASTED_URL]    # exchange the pasted redirect URL
    agent2drive init <slot>             # slot root + MANIFEST.md
    agent2drive upload <slot> <file> [folder] [--replace]
    agent2drive ls <slot>
    agent2drive manifest <slot>

The paste-back OAuth flow keeps the redirect on the user's machine; the
agent only ever sees a single-use code. Scope is drive.file (least
privilege). Tokens are written to state/rclone/rclone.conf (chmod 600),
which is gitignored and never printed.

Self-restoring: a missing or wrong-architecture rclone binary is
re-downloaded for the current platform. Only the refresh token is
irreplaceable — losing it means one fresh consent click, and nothing on
Drive is affected.
"""
import argparse
import base64
import binascii
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _default_home():
    """Source checkouts keep state beside the code; pip installs use XDG."""
    override = os.environ.get("A2D_HOME")
    if override:
        return Path(override).expanduser()
    if (BASE / "pyproject.toml").exists():
        return BASE
    config = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config).expanduser() if config else Path.home() / ".config"
    return root / "agent2drive"


HOME = _default_home()
STATE = HOME / "state/rclone"
CONF = STATE / "rclone.conf"
CLIENT = STATE / "client.json"
OAUTH_STATE = STATE / "oauth_state.json"
BIN = HOME / ("bin/rclone.exe" if os.name == "nt" else "bin/rclone")
STAGING = HOME / ".tmp/rclone-selfrestore"
ROOT = os.environ.get("GDRIVE_ROOT", "AgentDeliveries")

REDIRECT = "http://127.0.0.1:53682/"
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL = 15 * 60  # seconds; OAuth codes expire in ~10 minutes

# rclone's published default OAuth client (open source constants, not secrets).
# Prefer your own client via `agent2drive client` — see README.
CID_PREFIX = "202264815644-"
OBS_PREFIX = "eX8GpZTV"
AES_KEY = bytes([
    0x9c, 0x93, 0x5b, 0x48, 0x73, 0x0a, 0x55, 0x4d,
    0x6b, 0xfd, 0x7c, 0x63, 0xc8, 0x86, 0xa9, 0x2b,
    0xd3, 0x90, 0x19, 0x8e, 0xb8, 0x12, 0x8a, 0xfb,
    0xf4, 0xde, 0x16, 0x2b, 0x8b, 0x95, 0xf6, 0x38,
])

_ARCH = {
    "x86_64": "amd64", "amd64": "amd64", "i386": "386", "i686": "386",
    "aarch64": "arm64", "arm64": "arm64",
}


# ---------------------------------------------------------------- platform
def platform_suffix():
    """rclone download suffix for this machine, e.g. linux-arm64."""
    system = platform.system().lower()
    arch = _ARCH.get(platform.machine().lower())
    if not arch:
        raise SystemExit(f"[agent2drive] unsupported CPU: "
                         f"{platform.machine()!r} — set RCLONE_ZIP to a "
                         "rclone zip URL for your platform")
    if system == "linux":
        return f"linux-{arch}"
    if system == "darwin":
        return f"osx-{arch}"
    if system == "windows":
        return f"windows-{arch}"
    raise SystemExit(f"[agent2drive] unsupported OS: {system!r}")


def rclone_zip_url():
    override = os.environ.get("RCLONE_ZIP")
    return override or ("https://downloads.rclone.org/"
                        f"rclone-current-{platform_suffix()}.zip")


RCLONE_ZIP = rclone_zip_url()  # kept for compatibility; use rclone_zip_url()


def _expected_arch_tokens():
    arch = _ARCH.get(platform.machine().lower(), "")
    if arch == "arm64":
        return ("aarch64", "arm64")
    if arch == "amd64":
        return ("x86-64", "x86_64", "amd64")
    return ()


def _binary_ok(path):
    """Reject a cached/downloaded binary for the wrong CPU."""
    if os.name == "nt":
        return True
    try:
        out = subprocess.run(["file", "-b", str(path)],
                             capture_output=True, text=True,
                             timeout=15).stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return True  # no `file` available: fall back to the version probe
    tokens = _expected_arch_tokens()
    return not tokens or any(t in out for t in tokens)


def _runs(path):
    try:
        return subprocess.run([str(path), "version"], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------- restore
def _ensure_rclone():
    if BIN.exists() and _binary_ok(BIN) and _runs(BIN):
        return BIN
    if BIN.exists():
        print("[agent2drive] cached rclone is unusable or wrong-architecture "
              "- replacing it")
        BIN.unlink()
    print(f"[agent2drive] rclone missing - restoring for "
          f"{platform_suffix() if not os.environ.get('RCLONE_ZIP') else 'RCLONE_ZIP'}…")
    STAGING.mkdir(parents=True, exist_ok=True)
    zip_path = STAGING / "rclone.zip"
    req = urllib.request.Request(rclone_zip_url(),
                                 headers={"User-Agent": "agent2drive/0.3.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        zip_path.write_bytes(r.read())
    with zipfile.ZipFile(zip_path) as z:
        suffix = "/rclone.exe" if os.name == "nt" else "/rclone"
        member = next(n for n in z.namelist() if n.endswith(suffix))
        data = z.read(member)
    BIN.parent.mkdir(parents=True, exist_ok=True)
    tmp = BIN.with_suffix(".new")
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    if not _binary_ok(tmp) or not _runs(tmp):
        tmp.unlink()
        raise SystemExit("[agent2drive] downloaded rclone failed its "
                         "architecture/startup check — check RCLONE_ZIP")
    tmp.replace(BIN)
    print(f"[agent2drive] restored {BIN}")
    return BIN


def _rc(*args, timeout=900, check=True, stdin_data=None, retries=0):
    """Single choke point for every rclone call (also makes tests easy)."""
    _ensure_rclone()
    last = None
    for attempt in range(retries + 1):
        try:
            p = subprocess.run([str(BIN), "--config", str(CONF), *args],
                               capture_output=True, text=True,
                               timeout=timeout, input=stdin_data)
        except subprocess.TimeoutExpired:
            last = RuntimeError(f"rclone {' '.join(args[:2])} timed out "
                                f"after {timeout}s")
        except OSError as e:
            last = RuntimeError(f"cannot run rclone: {e}")
        else:
            if not check or p.returncode == 0:
                return p
            last = RuntimeError(f"rclone {' '.join(args[:2])} failed: "
                                f"{p.stderr.strip()[-400:]}")
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise last


# ------------------------------------------------------- OAuth client
def reveal(obscured):
    """Reverse rclone's 'obscure' encoding (AES-256-CTR, base64url)."""
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
    """Last-resort fallback: derive rclone's public default client secret."""
    out = _binary_strings()
    lines = out.splitlines()
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
    cands.sort(key=len)
    for cand in cands:
        if _google_accepts_client(client_id, cand):
            return cand
    raise SystemExit("[agent2drive] could not derive the OAuth client "
                     "secret from the rclone binary — run `agent2drive "
                     "client <id> <secret>` with your own client instead")


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
        try:
            d = json.loads(CLIENT.read_text())
            if d["client_id"] and d["client_secret"]:
                return d["client_id"], d["client_secret"]
        except (ValueError, KeyError, OSError):
            print("[agent2drive] client.json is unreadable; deriving again")
    out = _binary_strings()
    cid_re = re.compile(r"[0-9A-Za-z_\-]{20,}\.apps\.googleusercontent\.com")
    m = cid_re.search(out)
    if not m:
        raise SystemExit("[agent2drive] client id not found in binary — "
                         "run `agent2drive client <id> <secret>`")
    client_id = m.group(0)
    print(f"[agent2drive] deriving shared OAuth client ({client_id[:24]}…) — "
          "rclone's shared client is being retired; set your own with "
          "`agent2drive client`")
    secret = _client_secret_from_binary(client_id)
    set_client(client_id, secret)
    return client_id, secret


def set_client(client_id, secret):
    if not client_id or not secret or not isinstance(client_id, str) \
            or not isinstance(secret, str):
        raise SystemExit("[agent2drive] both client id and secret are required")
    STATE.mkdir(parents=True, exist_ok=True)
    CLIENT.write_text(json.dumps({"client_id": client_id.strip(),
                                  "client_secret": secret.strip()}))
    CLIENT.chmod(0o600)
    print("[agent2drive] CLIENT_WRITTEN (chmod 600)")


# ------------------------------------------------------------ OAuth flow
def new_oauth_state():
    """Generate and store a one-time nonce for the paste-back flow."""
    token = secrets.token_urlsafe(24)
    STATE.mkdir(parents=True, exist_ok=True)
    OAUTH_STATE.write_text(json.dumps({"state": token, "ts": time.time()}))
    OAUTH_STATE.chmod(0o600)
    return token


def check_oauth_state(pasted):
    """Verify the state in the pasted redirect; allow bare codes with warning."""
    m = re.search(r"[?&]state=([^&]+)", pasted or "")
    if not m:
        print("[agent2drive] warning: no state in pasted text (bare code "
              "accepted for compatibility)")
        return True
    pasted_state = urllib.parse.unquote(m.group(1))
    try:
        saved = json.loads(OAUTH_STATE.read_text())
        ok = (saved.get("state") == pasted_state
              and time.time() - saved.get("ts", 0) < STATE_TTL)
    except (OSError, ValueError, TypeError):
        ok = False
    if not ok:
        raise SystemExit("[agent2drive] OAuth state mismatch or expired — "
                         "run `agent2drive url` again and paste the fresh "
                         "redirect")
    OAUTH_STATE.unlink(missing_ok=True)
    return True


def consent_url(client_id, state=None):
    state = state if state is not None else "agent2drive"
    return "https://accounts.google.com/o/oauth2/v2/auth?" + \
        urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": REDIRECT,
            "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state})


def parse_code(pasted):
    m = re.search(r"[?&]code=([^&]+)", pasted or "")
    code = urllib.parse.unquote(m.group(1)) if m else (pasted or "").strip()
    code = code.strip().strip("'\"")
    if not code:
        raise SystemExit("[agent2drive] no code found in the pasted text")
    return code


def exchange(pasted):
    """Single-use OAuth code -> refresh token -> rclone.conf (chmod 600)."""
    check_oauth_state(pasted)
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
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(f"[agent2drive] token exchange failed: {e}") from None
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
    try:
        result = status(retries=2, quiet=True)
    except Exception as e:  # never lose a good token to a flaky verify
        print(f"[agent2drive] credentials saved, but verification failed: {e}")
        return "SAVED_UNVERIFIED"
    if result != "AUTH_OK":
        print("[agent2drive] credentials saved, but live verification "
              "failed — check `agent2drive status`")
        return "SAVED_UNVERIFIED"
    return result


# ----------------------------------------------------------------- cmds
def status(retries=0, quiet=False):
    if not CONF.exists():
        if not quiet:
            print("AUTH_MISSING — run `agent2drive url`, then "
                  "`agent2drive connect <pasted-url>`")
        return "AUTH_MISSING"
    try:
        line = (_rc("about", "gdrive:", timeout=120, retries=retries)
                .stdout.strip().splitlines() or [""])[-1]
        if not quiet:
            print(f"AUTH_OK — {line.strip()}")
        return "AUTH_OK"
    except (RuntimeError, OSError) as e:
        if not quiet:
            print(f"AUTH_MISSING ({e})")
        return "AUTH_MISSING"


def _check_slot(slot):
    if (not slot or slot in (".", "..") or "/" in slot or "\\" in slot
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slot)):
        raise SystemExit(f"[agent2drive] invalid slot name: {slot!r} "
                         "(lowercase letters, digits and hyphens, "
                         "max 64 chars)")
    return slot


def _check_folder(folder):
    """No imposed structure; any single path component is valid."""
    if folder is None:
        return None
    if (not folder or folder in (".", "..") or "/" in folder
            or "\\" in folder or folder.strip() != folder):
        raise SystemExit(f"[agent2drive] invalid folder name: {folder!r} "
                         "(one path component; no /, \\, '..', "
                         "surrounding spaces)")
    return folder


def _remote_dir(slot, folder=None):
    slot = _check_slot(slot)
    folder = _check_folder(folder)
    return f"{ROOT}/{slot}" + (f"/{folder}" if folder else "")


def _manifest_remote(slot):
    return f"gdrive:{ROOT}/{_check_slot(slot)}/MANIFEST.md"


def _manifest_header(slot):
    return (f"# {slot} — delivery manifest\n\n"
            "UTC | File | Folder | Bytes | MD5 | SHA-1 | Result\n"
            "--- | --- | --- | --- | --- | --- | ---\n")


def _read_manifest(slot):
    p = _rc("cat", _manifest_remote(slot), check=False, timeout=120)
    text = p.stdout if p.returncode == 0 else ""
    # Migrate the legacy prose-only MANIFEST.md written by <= 0.2.0.
    if "UTC | File | Folder" not in text:
        return _manifest_header(slot)
    return text


def _append_manifest(slot, row):
    text = _read_manifest(slot)
    if not text.endswith("\n"):
        text += "\n"
    _rc("rcat", _manifest_remote(slot), stdin_data=text + row + "\n",
        timeout=120)


def cmd_init(slot):
    _check_slot(slot)
    _rc("mkdir", f"gdrive:{ROOT}/{slot}")
    _rc("rcat", _manifest_remote(slot),
        stdin_data=_manifest_header(slot), timeout=120)
    print(f"[agent2drive] slot ready: gdrive:{ROOT}/{slot}/")


def _local_hashes(path):
    md5, sha1 = hashlib.md5(), hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)
            sha1.update(chunk)
    return md5.hexdigest(), sha1.hexdigest()


def _remote_hashes(remote):
    """Drive serves MD5/SHA-1 natively; return whatever rclone can read."""
    out = {}
    for algo, length in (("MD5", 32), ("SHA-1", 40)):
        p = _rc("hashsum", algo, remote, check=False, timeout=300)
        if p.returncode:
            continue
        m = re.search(r"\b([0-9a-fA-F]{%d})\b" % length, p.stdout)
        if m:
            out[algo] = m.group(1).lower()
    return out


def _remote_files(remote_dir):
    p = _rc("lsjson", "--files-only", f"gdrive:{remote_dir}",
            check=False, timeout=300)
    if p.returncode:
        return []
    try:
        return json.loads(p.stdout)
    except ValueError:
        return []


def cmd_upload(slot, path, folder=None, replace=False):
    remote_dir = _remote_dir(slot, folder)
    src = Path(path)
    if not src.is_file():
        raise SystemExit(f"[agent2drive] not a file: {src}")
    remote = f"gdrive:{remote_dir}/{src.name}"
    size = src.stat().st_size
    md5, sha1 = _local_hashes(src)

    existing = next((i for i in _remote_files(remote_dir)
                     if i.get("Name") == src.name), None)
    if existing and not replace:
        raise SystemExit(f"[agent2drive] {remote} already exists — "
                         "use --replace to overwrite it")

    print(f"[agent2drive] uploading {src.name} ({size} B) -> {remote}")
    _rc("copyto", str(src), remote, retries=1)

    remote_hashes = _remote_hashes(remote)
    remote_size = next((i["Size"] for i in _remote_files(remote_dir)
                        if i.get("Name") == src.name), None)
    def matches(remote, local):
        return None if remote is None else remote == local

    checks = {
        "size": matches(remote_size, size),
        "MD5": matches(remote_hashes.get("MD5"), md5),
        "SHA-1": matches(remote_hashes.get("SHA-1"), sha1),
    }
    if any(v is False for v in checks.values()):
        _rc("deletefile", remote, check=False)
        raise SystemExit(f"[agent2drive] verification FAILED for {src.name}: "
                         f"size={size}/{remote_size} "
                         f"md5={md5}/{remote_hashes.get('MD5')} "
                         f"sha1={sha1}/{remote_hashes.get('SHA-1')} "
                         "— remote copy removed; retry the upload")
    if any(v is None for v in checks.values()):
        result = "SIZE-ONLY"
        print("[agent2drive] warning: remote hashes unavailable; only size "
              "was verified")
    else:
        result = "OK"
    print(f"[agent2drive] verified: size {checks['size']} · "
          f"md5 {checks['MD5']} · sha1 {checks['SHA-1']} -> {result}")

    safe_name = src.name.replace("|", "\\|")
    row = "| " + " | ".join([
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        safe_name, folder or "-", str(size), md5, sha1, result]) + " |"
    _append_manifest(slot, row)
    print(f"[agent2drive] manifest updated: gdrive:{ROOT}/{slot}/MANIFEST.md")
    return 0 if result == "OK" else 1


def cmd_ls(slot):
    _check_slot(slot)
    p = _rc("lsf", "-R", "--files-only", f"gdrive:{ROOT}/{slot}/",
            timeout=300)
    print(p.stdout or "(empty)")
    return 0


def cmd_manifest(slot):
    print(_read_manifest(slot), end="")
    return 0


CONNECT_RECIPE = """AUTH_MISSING — one-time connect:
  1. agent2drive url             -> give the user the printed URL
  2. user: open URL -> Allow -> browser fails on 127.0.0.1:53682
     (EXPECTED) -> copy the full address-bar URL
  3. agent2drive connect '<PASTED_URL>'
  (recommended: agent2drive client <id> <secret> first, with your own client)"""


def cli(argv=None):
    parser = argparse.ArgumentParser(
        prog="agent2drive",
        description="Connect an agent to Google Drive and upload reviewable files.")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="check the live connection (exit 0/2)")
    sub.add_parser("url", help="print the Google consent URL")

    c = sub.add_parser("connect", help="exchange a pasted redirect URL/code")
    c.add_argument("pasted", nargs="?", help="full pasted URL, or '-' for stdin")
    c.add_argument("--stdin", action="store_true", help="read the code from stdin")

    cl = sub.add_parser("client", help="set your own OAuth client id/secret")
    cl.add_argument("client_id", nargs="?")
    cl.add_argument("client_secret", nargs="?")

    i = sub.add_parser("init", help="create a slot root + MANIFEST.md")
    i.add_argument("slot")

    u = sub.add_parser("upload", help="upload and verify a file into a slot")
    u.add_argument("slot")
    u.add_argument("file")
    u.add_argument("folder", nargs="?")
    u.add_argument("--replace", action="store_true",
                   help="overwrite an existing file of the same name")

    ls = sub.add_parser("ls", help="list a slot's files")
    ls.add_argument("slot")

    m = sub.add_parser("manifest", help="print a slot's delivery manifest")
    m.add_argument("slot")

    args = parser.parse_args(argv)
    if not args.cmd:
        status(quiet=True)
        print(CONNECT_RECIPE)
        return 2

    if args.cmd == "status":
        return 0 if status() == "AUTH_OK" else 2
    if args.cmd == "url":
        client_id, _ = load_client()
        print(consent_url(client_id, new_oauth_state()))
        return 0
    if args.cmd == "connect":
        pasted = args.pasted
        if args.stdin or pasted == "-":
            pasted = sys.stdin.read().strip()
        if not pasted:
            parser.error("connect needs a pasted URL/code (or --stdin)")
        result = exchange(pasted)
        return 0 if result in ("AUTH_OK", "SAVED_UNVERIFIED") else 1
    if args.cmd == "client":
        cid = args.client_id or input("OAuth client id: ").strip()
        secret = args.client_secret or getpass.getpass("OAuth client secret: ")
        set_client(cid, secret)
        return 0
    if args.cmd == "init":
        cmd_init(args.slot)
        return 0
    if args.cmd == "upload":
        return cmd_upload(args.slot, args.file, args.folder, args.replace)
    if args.cmd == "ls":
        return cmd_ls(args.slot)
    if args.cmd == "manifest":
        return cmd_manifest(args.slot)
    parser.print_help()
    return 1


def main(argv=None):
    return cli(argv)


if __name__ == "__main__":
    sys.exit(cli())

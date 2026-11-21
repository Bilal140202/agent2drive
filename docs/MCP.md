# MCP server

Implemented in **0.4.0**. The server is a thin stdio adapter over the core `agent2drive.py` functions — there is no second OAuth or verification implementation.

## Install

```sh
pipx install 'agent2drive[mcp]'
# or: python3 -m pip install --user 'agent2drive[mcp]'
```

Confirm it starts: `agent2drive-mcp` (it speaks JSON-RPC on stdio and prints nothing else).

## OpenCode setup

```sh
opencode mcp add agent2drive -- agent2drive-mcp
```

With environment variables:

```sh
opencode mcp add agent2drive \
  --env A2D_HOME=/home/ubuntu/.config/agent2drive \
  --env A2D_ALLOWED_ROOTS=/home/ubuntu/projects \
  -- agent2drive-mcp
```

Hand-written config:

```jsonc title="opencode.jsonc"
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "agent2drive": {
        "type": "local",
        "command": ["agent2drive-mcp"],
        "environment": {
          "A2D_HOME": "{env:A2D_HOME}",
          "A2D_ALLOWED_ROOTS": "{env:A2D_ALLOWED_ROOTS}"
        }
      }
    }
  }
}
```

OpenCode names tools `agent2drive_a2d_status`, etc.; in Code Mode they appear as `tools.agent2drive.a2d_status(...)`. Check the connection with `opencode mcp list`.

For other MCP hosts, register a local stdio server with command `agent2drive-mcp`.

## Environment

| Variable | Meaning |
| --- | --- |
| `A2D_HOME` | Where state, rclone binary and temp files live (default: XDG config dir for pip installs, repo dir for checkouts) |
| `A2D_ALLOWED_ROOTS` | `os.pathsep`-separated list of local directories the server may upload from (default: process working directory) |
| `GDRIVE_ROOT` | Drive root folder name (default `AgentDeliveries`) |

## Tools

| Tool | Input | Result |
| --- | --- | --- |
| `a2d_status` | — | `AUTH_OK` / `AUTH_MISSING` |
| `a2d_set_client` | `client_id`, `client_secret` | secret stored, never echoed |
| `a2d_consent_url` | — | consent URL + one-time state nonce |
| `a2d_connect` | `pasted_url` | auth result; state consumed |
| `a2d_init_slot` | `slot` | slot root + manifest created |
| `a2d_upload` | `slot`, `path`, `folder?`, `replace?`, `confirm?` | size/MD5/SHA-1 result + manifest row |
| `a2d_list` | `slot` | file list |
| `a2d_manifest` | `slot` | delivery history |

Responses are structured JSON (`ok`, `code`, `message`, `data`). Core functions' `print()` output is captured and returned in `data.log`, so it cannot corrupt the stdio JSON-RPC stream.

## Resources and prompt

- `a2d://config` — non-secret configuration (version, Drive root, allowed roots).
- `a2d://slot/{slot}/manifest` — delivery manifest.
- Prompt `deliver-file` — "create the file, call `a2d_upload`, report the verification result and where to review it".

## Security controls

- **stdio only.** No HTTP listener or network attack surface.
- **User-mediated auth.** The model can print a consent URL but cannot complete consent; tokens and client secrets never appear in tool responses.
- **Path allowlist.** `A2D_ALLOWED_ROOTS` restricts uploads; symlinks are resolved so a link can't escape. Slot/folder names use the strict core validators.
- **Overwrite gate.** `replace=True` requires `confirm="REPLACE"`.
- **Redaction.** Client secrets, refresh tokens and OAuth codes are never returned in results.
- **Audit trail.** The Drive-side `MANIFEST.md` records every verified delivery with hashes and timestamps. A separate local tool-call audit log is not implemented yet.

## Tests

`tests/test_agent2drive_mcp.py` covers tool registration, stdout capture, `SystemExit` handling, symlink-aware path allowlisting, replace confirmation, secret redaction, and the config resource. Verification also includes a live MCP client handshake over stdio (initialize → list tools → call tools).

## Deferred / open questions

- Remote transport (streamable HTTP with short-lived bearer tokens) behind a flag.
- Local tool-call audit log in addition to the Drive manifest.
- Local `agent2drive.toml` for per-project slot/root configuration.
- Concurrent uploads to the same slot: local lock plus re-read before manifest append.

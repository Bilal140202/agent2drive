# MCP plan (proposed)

Goal: let an agent deliver files to Google Drive through MCP tool calls instead of shell commands, while keeping the user's Google credentials completely out of the model's context.

## Design principles

1. **stdio transport only, initially.** No HTTP listener, no network attack surface. The agent launches `agent2drive-mcp` as a local child process.
2. **User-mediated auth.** The model may call `a2d_consent_url`, but only the user can click Allow and paste the redirect. `a2d_connect` accepts that pasted URL once. Tokens and client secrets are never returned by a tool.
3. **Reuse the core module.** The MCP server is a thin adapter over the functions in `agent2drive.py` (`status`, `exchange`, `cmd_init`, `cmd_upload`, `cmd_ls`, `cmd_manifest`). No second implementation of the OAuth or verification logic.
4. **Explicit destructive actions.** Overwrites and deletes require an explicit `replace: true` plus a confirmation token from the host app.

## Prerequisite (done in 0.3.0)

State must not live in `site-packages`. `A2D_HOME` (falling back to XDG config for pip installs) now controls where `state/`, `bin/` and `.tmp/` live, so a pip-installed MCP server and the CLI share one token store.

## Packaging

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0"]

[project.scripts]
agent2drive-mcp = "agent2drive_mcp:main"
```

Install with `pipx install 'agent2drive[mcp]'` or `pip install 'agent2drive[mcp]'`.

## Tools

| Tool | Input | Result |
| --- | --- | --- |
| `a2d_status` | — | `AUTH_OK` / `AUTH_MISSING`, quota summary |
| `a2d_set_client` | `client_id`, `client_secret` | confirms secret stored, never echoes it |
| `a2d_consent_url` | — | consent URL + one-time state nonce issued |
| `a2d_connect` | `pasted_url` | auth result or clear error; state consumed |
| `a2d_init_slot` | `slot` | slot root + manifest created |
| `a2d_upload` | `slot`, `path`, `folder?`, `replace?`, `confirm?` | size/MD5/SHA-1 result, manifest row, remote path |
| `a2d_list` | `slot` | file list |
| `a2d_manifest` | `slot` | delivery history |

Each tool returns structured JSON including `ok`, `code`, `message`, and `data`. Errors never include token material.

## Resources and prompts

- `a2d://slots` — known local slot configurations.
- `a2d://slot/{slot}/files` — cached file listing.
- `a2d://slot/{slot}/manifest` — delivery manifest text.
- Prompt `deliver-file` — "create the file, call `a2d_upload`, report the verification result and where to review it".

## Security controls

- `A2D_ALLOWED_ROOTS`: allowlist of local directories the server may read files from. Uploading `/etc/passwd` must be refused even if the model asks.
- Slot/folder names go through the existing strict validators; no traversal.
- `replace` without an explicit host confirmation is rejected.
- Tool responses redact `client_secret`, `refresh_token`, and the OAuth code.
- An append-only local audit log records tool name, arguments (redacted), timestamp, and result.
- Scoped Drive access remains `drive.file`; no broader scope is ever requested.

## Rollout

1. **Thin stdio server** with the tool table above, using direct function calls and the existing `_rc()` choke point. Tests with the injected fake rclone.
2. **Resources and prompt templates**, plus configuration docs for OpenCode, Claude Desktop, and other MCP hosts.
3. **Policy layer** (`A2D_ALLOWED_ROOTS`, confirmation tokens, audit log) and adversarial tests: path traversal, secret leakage, replayed OAuth state, overwrite without confirmation.
4. **Optional remote transport** (streamable HTTP with short-lived bearer tokens) only if there's a real need; it stays behind a flag.

## Open questions

- Should slot configuration live in a local `agent2drive.toml` (per project) in addition to env vars?
- Should the server maintain a local index of uploaded hashes for instant "what changed?" queries, or treat Drive as the only source of truth?
- How should manifest conflicts be resolved when two agents upload to the same slot concurrently? (A local lock plus server-side re-read before append is the likely answer.)

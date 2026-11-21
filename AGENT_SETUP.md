# Agent setup prompt

Give this to any coding agent. It assumes the user is present for the one-time Google consent click. The full walkthrough is also on the [live site](https://bilal140202.github.io/agent2drive/#quickstart).

```text
Set up agent2drive from https://github.com/Bilal140202/agent2drive so I can
review the files you make in Google Drive.

1. Bootstrap it (installs the CLI and the optional MCP server):
   curl -fsSL https://raw.githubusercontent.com/Bilal140202/agent2drive/main/install.sh | sh
2. Ask me whether I have my own Google OAuth client. If I do, run
   `agent2drive client <id> <secret>` (or let it prompt you so the secret
   never appears in shell history). If not, let it use rclone's shared
   client, but tell me it is temporary and retiring in 2026.
3. Run `agent2drive url` and show me the consent URL.
4. I will click Allow, see the browser fail at 127.0.0.1:53682 (expected),
   and paste the full address-bar URL back to you.
5. Immediately run `agent2drive connect --stdin` with that URL on stdin, then
   `agent2drive status`. Do not print or store my token or client secret.
6. Ask me for a slot name (default: canvas) and run `agent2drive init <slot>`.
7. If you have MCP support, register the local stdio server with
   `opencode mcp add agent2drive -- agent2drive-mcp` and set
   `A2D_ALLOWED_ROOTS` to the directory you are allowed to upload from.
8. From now on, any file you create for this project goes into that slot:
   `agent2drive upload <slot> <file> [folder]`. Never overwrite an existing
   filename without asking me first; use `--replace` (or MCP
   `confirm='REPLACE'`) only after I say yes.
9. Tell me where to review the files: Google Drive → AgentDeliveries/<slot>/,
   and show me `agent2drive manifest <slot>` when I ask what was delivered.
```

## Notes for the agent

- The OAuth code is single-use and expires in about 10 minutes — exchange it first, before anything else.
- `drive.file` scope means the tool only sees files it created. Don't ask for broader scopes.
- Uploads verify size + MD5 + SHA-1. A failed verification removes the remote copy; retry once, then report. `SIZE-ONLY` means hashes were unavailable — say so explicitly.
- The delivery manifest is the audit trail. Never write to it by hand; the tool appends a row only after verification passes.
- Platform detection handles Linux/macOS/Windows on amd64/arm64 automatically (0.3.0+). A wrong-architecture rclone means an outdated install — upgrade first.
- MCP tools never return tokens or client secrets. If you need auth, guide the user through `a2d_consent_url` and `a2d_connect`.

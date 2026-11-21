---
name: agent2drive
description: Set up or use agent2drive to deliver files to the user's Google Drive for review (upload verified files, create slots, read manifests, or walk through the one-time OAuth paste-back flow). Use when the user asks to set up a review canvas, send files to Drive, upload deliverables, or check what has been delivered. Not for editing the user's existing Drive documents.
metadata:
  opencode/autoinvoke: true
---

# agent2drive

Deliver files into the user's Google Drive so they can review them.

## Setup (once)

1. Bootstrap: `curl -fsSL https://raw.githubusercontent.com/Bilal140202/agent2drive/main/install.sh | sh`.
2. Prefer the user's own OAuth client: `agent2drive client <id> <secret>` (or run without args to be prompted). Never print the secret.
3. Run `agent2drive url` and give the user the URL. They click Allow; the browser "fails" on `127.0.0.1:53682` — expected. They paste the full address-bar URL back.
4. Exchange it immediately: `agent2drive connect --stdin` with the pasted URL on stdin, then `agent2drive status`.
5. Ask for a slot name (default `canvas`) and run `agent2drive init <slot>`.
6. If the host supports MCP, register the server:
   `opencode mcp add agent2drive -- agent2drive-mcp`, and set
   `A2D_ALLOWED_ROOTS` to the directory you may upload from.

## Every delivery

- Create the file in the working directory as usual.
- `agent2drive upload <slot> <file> [folder]` — folder is optional and one component only (e.g. `drafts`, `final`).
- Uploads verify size, MD5 and SHA-1. `OK` means verified; `SIZE-ONLY` means hashes were unavailable — report that.
- Do not overwrite an existing filename without the user's approval; use `--replace` only after they agree.
- Use `agent2drive manifest <slot>` to report what was delivered and when.

## Security

- Scope is `drive.file`; never ask for broader Drive access.
- Tokens and client secrets are chmod 600 and gitignored. Never echo them.
- The OAuth state nonce is one-time; if `connect` reports a mismatch, generate a fresh URL.
- MCP tools never return secrets; auth still requires the user's click and paste. Uploads require `confirm='REPLACE'` to overwrite.
- Full docs: <https://bilal140202.github.io/agent2drive/> and `docs/MCP.md`.

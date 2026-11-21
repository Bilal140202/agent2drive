# Agent setup prompt

Give this to any coding agent. It assumes the user is present for the one-time Google consent click.

```text
Set up agent2drive from https://github.com/Bilal140202/agent2drive so I can
review the files you make in Google Drive.

1. Bootstrap it:
   curl -fsSL https://raw.githubusercontent.com/Bilal140202/agent2drive/main/install.sh | sh
2. Ask me whether I have my own Google OAuth client. If I do, run
   `agent2drive client <id> <secret>` (or let it prompt you). If not, let it
   use rclone's shared client but tell me it is temporary.
3. Run `agent2drive url` and show me the consent URL.
4. I will click Allow, see the browser fail at 127.0.0.1:53682 (expected),
   and paste the full address-bar URL back to you.
5. Immediately run `agent2drive connect --stdin` with that URL on stdin, then
   `agent2drive status`. Do not print or store my token or client secret.
6. Ask me for a slot name (default: canvas) and run `agent2drive init <slot>`.
7. From now on, any file you create for this project goes into that slot:
   `agent2drive upload <slot> <file> [folder]`. Never overwrite an existing
   filename without asking me first; use `--replace` only after I say yes.
8. Tell me where to review the files: Google Drive → AgentDeliveries/<slot>/.
```

## Notes for the agent

- The OAuth code is single-use and expires in about 10 minutes — exchange it first, before anything else.
- `drive.file` scope means the tool only sees files it created. Don't ask for broader scopes.
- Uploads verify size + MD5 + SHA-1. A failed verification removes the remote copy; retry once, then report.
- The delivery manifest is the audit trail. Show it with `agent2drive manifest <slot>` when asked what was delivered.
- If the machine is ARM and the tool restores an amd64 rclone, that is a pre-0.3.0 bug: upgrade first.

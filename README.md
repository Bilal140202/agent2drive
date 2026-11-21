# agent2drive

**One command connects an agent to your Google Drive. One command per upload. That's the whole product.**

An agent writes files locally; you review them in Drive. No video-generation model, no stock footage, no public redirect server, no broad Drive access — just a narrow `drive.file` scope and a paste-back OAuth code.

## Install

```sh
pipx install agent2drive                 # recommended
# or
python3 -m pip install --user agent2drive
```

One-line bootstrap for an agent to run for you:

```sh
curl -fsSL https://raw.githubusercontent.com/Bilal140202/agent2drive/main/install.sh | sh
```

See [AGENT_SETUP.md](AGENT_SETUP.md) for the exact prompt to give an agent; [skills/agent2drive/SKILL.md](skills/agent2drive/SKILL.md) is a drop-in skill for OpenCode/Claude-style agents.

## Connect (one time)

Using your own OAuth client is strongly recommended — rclone's shared public client is being retired during 2026. Create a Desktop OAuth client in Google Cloud with redirect URI `http://127.0.0.1:53682/`, then:

```sh
agent2drive client <client_id> <client_secret>   # stored chmod 600, gitignored
agent2drive url
```

1. Give the user the printed consent URL.
2. They click **Allow**. Google may warn " hasn't verified this app" → **Advanced → Go to rclone (unsafe) → Allow**.
3. The browser fails to load `127.0.0.1:53682`. **That failure is expected** — it only runs on the user's machine. They copy the full address-bar URL and paste it back.
4. You exchange it immediately (single-use, ~10-minute TTL):

```sh
agent2drive connect '<PASTED_URL>'
# or: agent2drive connect --stdin   (safer: keeps the code out of shell history)
agent2drive status
```

If you skip `client`, the tool falls back to deriving rclone's published default client from its own binary. It works today but is rate-limit-prone and will stop working when Google retires that client.

## Commands

| Command | What it does |
| --- | --- |
| `status` | Live token check (`AUTH_OK` / `AUTH_MISSING`, exit 0/2) |
| `url` | Print the consent URL and store a one-time state nonce |
| `client [ID] [SECRET]` | Set your own OAuth client (prompts if omitted) |
| `connect [URL]` / `connect --stdin` | Exchange the pasted redirect URL |
| `init <slot>` | Create a slot root and `MANIFEST.md` |
| `upload <slot> <file> [folder] [--replace]` | Upload, verify, and log to the manifest |
| `ls <slot>` | List everything in a slot |
| `manifest <slot>` | Print the delivery manifest |

## Verified uploads — not just size

The original release claimed "byte-exact verification" but only compared file sizes. Now every upload is checked three ways:

- **size** from `rclone lsjson`
- **MD5** and **SHA-1** from `rclone hashsum` (both natively supported by Google Drive)

A mismatch deletes the remote copy, fails loudly, and writes nothing to the manifest. If hashes can't be read, the manifest records `SIZE-ONLY` and the command exits non-zero. These hashes detect accidental corruption; they are not a cryptographic authenticity guarantee.

Same-name uploads **fail by default**. Pass `--replace` to overwrite deliberately, so a reviewer isn't silently robbed of an earlier draft.

## Slots and the manifest

Everything lives under one root (default `AgentDeliveries`, override with `GDRIVE_ROOT`), one folder per project:

```
AgentDeliveries/
  <slot>/
    MANIFEST.md
    <your folders>/       created on demand; one component, no traversal
```

`init` creates only the slot root and manifest — no imposed category tree. Every successful upload appends a row with UTC time, filename, folder, bytes, MD5, SHA-1, and result. That gives you an audit trail of what the agent delivered and when. Slot names are restricted to lowercase letters, digits and hyphens; path traversal is rejected.

## Self-restoring, cross-platform

A missing or wrong-architecture rclone binary is re-downloaded for the current platform (`linux-amd64`, `linux-arm64`, `osx-*`, `windows-*`), architecture-checked, and smoke-tested before use. Override with `RCLONE_ZIP=<url>` for unusual platforms.

The refresh token in `state/rclone/rclone.conf` (chmod 600, gitignored) is the only thing that can't be rebuilt. Lose it and one fresh consent click restores everything; nothing already on Drive is affected.

State lives beside the source in a checkout, and in `~/.config/agent2drive/` for a pip/pixi install (override with `A2D_HOME`, or `XDG_CONFIG_HOME`). Nothing is ever written into `site-packages`.

## Security

- Scope is `drive.file`: the agent can only see files it created itself.
- `state/`, `bin/`, and `.tmp/` are gitignored; tokens and OAuth client secrets are chmod 600 and never printed.
- The OAuth `state` nonce is random, stored locally, and checked on `connect` (15-minute TTL).
- Prefer `connect --stdin` so single-use codes don't land in shell history.
- Revoke access any time at <https://myaccount.google.com/> → Security → Third-party apps → rclone.

## MCP

See [docs/MCP.md](docs/MCP.md) for the planned MCP server: tools, resources, config, and rollout phases.

## Development

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Tests cover pure logic plus injected-rclone failure paths (hash mismatch, missing hashes, collisions, retries, state replay, and the post-connect crash regression).

## License

MIT. rclone is MIT-licensed; its published OAuth constants are used and credited per its license.

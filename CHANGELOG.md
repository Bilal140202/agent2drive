# Changelog

All notable changes. Dates are UTC.

## [0.4.1] - 2026-11-21

### Changed
- Documentation-only refresh: the GitHub Pages site now covers pip install, hash verification, the manifest, the own-client flow, cross-platform restore, `A2D_HOME`, and the MCP server with copy-paste setup.
- README, agent setup prompt, drop-in skill, and PyPI description now agree with the 0.4.0 feature set.
- `install.sh` installs the `mcp` extra by default.
- CI installs `requirements-dev.txt` and verifies the package build on every push.

## [0.4.0] - 2026-11-21

### Added
- **MCP server**: `agent2drive-mcp` (stdio, optional `mcp` extra) with 8 tools, `a2d://config` and `a2d://slot/{slot}/manifest` resources, and a `deliver-file` prompt. Works with MCP SDK v1 (`FastMCP`) and v2 (`MCPServer`), with structured output on v2.
- MCP safety: `A2D_ALLOWED_ROOTS` path allowlist with symlink resolution, `confirm='REPLACE'` gate for overwrites, secret redaction, and stdout capture so core `print()` calls can't corrupt JSON-RPC.
- OpenCode setup instructions for the local stdio server.

### Tests
- 8 new MCP tests; 31 total. Verified with a live MCP client handshake (initialize, list tools, call tools).

## [0.3.0] - 2026-11-21

### Added
- Real upload verification: size + MD5 + SHA-1 (Google Drive serves both hashes natively). Mismatches delete the remote copy and fail loudly; unavailable hashes are logged as `SIZE-ONLY` with a non-zero exit.
- Delivery manifest is updated after every successful upload (UTC time, file, folder, bytes, MD5, SHA-1, result). Legacy prose manifests are migrated automatically.
- `--replace` is now required to overwrite an existing file; plain uploads refuse collisions.
- Own OAuth client support via `agent2drive client [ID] [SECRET]` (prompts for the secret), plus a random one-time OAuth `state` nonce with a 15-minute TTL.
- `agent2drive connect --stdin` keeps single-use codes out of shell history.
- `agent2drive manifest <slot>` command and argparse-based CLI with `--help`.
- Cross-platform rclone restore: platform-detected zip (linux/osx/windows, amd64/arm64/386), architecture and startup checks, `RCLONE_ZIP` override.
- `A2D_HOME` / XDG state location so pip installs never write into `site-packages`.
- Pip packaging (`pyproject.toml`), `install.sh` bootstrap, `AGENT_SETUP.md`, a drop-in agent skill, and the MCP plan in `docs/MCP.md`.

### Fixed
- "Byte-exact verification" previously compared only file size.
- `connect` no longer crashes with a traceback after successfully saving credentials; verification failures now report `SAVED_UNVERIFIED`.
- Uploads with no folder no longer target a literal `None` directory.
- Slot names are validated; traversal and invalid characters are rejected.
- `status` prints a clear `AUTH_MISSING` message and retries transient rclone failures.

### Tests
- 23 tests covering pure logic, platform detection, OAuth state replay/expiry, injected-rclone upload paths (hash mismatch, missing hashes, collisions, manifest updates), retry behaviour, and the post-connect crash regression.

## [0.2.0] - 2026-11-17

### Changed
- **Breaking:** no imposed category tree. `init <slot>` creates only the slot root + MANIFEST.md; `upload <slot> <file> [folder]` accepts ANY folder name (single path component, created on demand) and defaults to the slot root when omitted. Previously a fixed video-production tree (master/shorts/subtitles/thumbnails/assets/backups) was forced on every slot — agent2drive is a generic Drive connector and the folder layout is the user's decision.

## [0.1.0] - 2026-11-17

### Added
- One-command connect (status/url/connect) with paste-back OAuth: rclone published default client, drive.file scope, token exchange first-then-everything-else, live quota verification.
- Slot system (init/upload/ls) with byte-exact size verification.
- Self-restore: rclone binary re-download, OAuth client re-derivation from the binary with Google-endpoint validation.
- Unit tests for reveal/parse/consent-url (no network in tests).

# Changelog

All notable changes. Dates are UTC.

## [0.2.0] - 2026-11-17

### Changed
- **Breaking:** no imposed category tree. `init <slot>` creates only
  the slot root + MANIFEST.md; `upload <slot> <file> [folder]` accepts
  ANY folder name (single path component, created on demand) and
  defaults to the slot root when omitted. Previously a fixed
  video-production tree (master/shorts/subtitles/thumbnails/assets/
  backups) was forced on every slot — agent2drive is a generic Drive
  connector and the folder layout is the user's decision.

## [0.1.0] - 2026-11-17

### Added
- One-command connect (status/url/connect) with paste-back OAuth:
  rclone published default client, drive.file scope, token exchange
  first-then-everything-else, live quota verification.
- Slot system (init/upload/ls) with byte-exact size verification.
- Self-restore: rclone binary re-download, OAuth client re-derivation
  from the binary with Google-endpoint validation.
- Unit tests for reveal/parse/consent-url (no network in tests).

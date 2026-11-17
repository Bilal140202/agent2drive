# Changelog

All notable changes. Dates are UTC.

## [0.1.0] - 2026-11-17

### Added
- One-command connect (status/url/connect) with paste-back OAuth:
  rclone published default client, drive.file scope, token exchange
  first-then-everything-else, live quota verification.
- Slot system (init/upload/ls) with byte-exact size verification.
- Self-restore: rclone binary re-download, OAuth client re-derivation
  from the binary with Google-endpoint validation.
- Unit tests for reveal/parse/consent-url (no network in tests).

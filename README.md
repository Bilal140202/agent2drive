# agent2drive

**One command connects an agent to your Google Drive. One command per
upload. That's the whole product.**

Built after doing the OAuth dance by hand one too many times: consent
URL, "Google hasn't verified this app", the browser landing on
`127.0.0.1` and failing, the single-use code expiring, the recycle wipe
throwing everything away. agent2drive compresses all of it into one
script that any agent (or human) can run — and that rebuilds itself
when the sandbox around it disappears.

```bash
python3 agent2drive.py                      # status — or the connect recipe
python3 agent2drive.py url                  # print the consent URL
python3 agent2drive.py connect '<PASTED_URL_OR_CODE>'
python3 agent2drive.py init <slot>          # folder tree on your Drive
python3 agent2drive.py upload <slot> <file> [category]
python3 agent2drive.py ls <slot>
```

## How connecting works (the honest, complete walkthrough)

Google pins the OAuth redirect to `http://127.0.0.1:53682/` — on the
**user's** machine. The agent's sandbox is a different machine, so the
redirect can never land there. agent2drive turns that limitation into a
3-step paste-back flow:

1. **`url`** — the script prints a consent URL. It uses rclone's
   published default OAuth client with the narrowest scope Google
   offers: `drive.file`.
2. **The user clicks Allow.** Google warns "Google hasn't verified this
   app" (expected for rclone's public client: Advanced → "Go to rclone
   (unsafe)" → Allow). The browser then fails to load
   `127.0.0.1:53682` — **that failure is the expected path**, because
   that address only exists on the user's machine.
3. **The user copies the full address-bar URL** (it now contains a
   `?code=4/...`) and pastes it to the agent. **`connect`** exchanges
   it — the code is single-use and expires in ~10 minutes, so this step
   runs first, before anything else — writes `state/rclone/rclone.conf`
   (chmod 600) and verifies the connection with a live quota check:

   ```
   [agent2drive] CONF_WRITTEN (chmod 600)
   AUTH_OK — Other: 131.712 GiB
   ```

If the user closes the tab or the code expires, run `url` again. That's
the whole ceremony.

## Commands

| Command | What it does |
| --- | --- |
| *(no args)* | `status`; when not connected, prints the 3-step recipe |
| `status` | checks the token live (`AUTH_OK` / `AUTH_MISSING`, exit 0/2) |
| `url` | builds + prints the consent URL |
| `connect <pasted>` | exchanges the code, writes the config, verifies |
| `init <slot>` | creates the slot folder tree + MANIFEST.md on Drive |
| `upload <slot> <file> [category]` | uploads and **verifies the size byte-exact** |
| `ls <slot>` | lists everything in the slot |

## Slots — where your files land

Everything lives under one root folder (default `AgentDeliveries`;
change with the `GDRIVE_ROOT` env var), one folder per project:

```
AgentDeliveries/
  <slot>/                e.g. clipforge, ep3-amelia, q3-report
    MANIFEST.md
    master/              final long-form renders
    shorts/              vertical cuts
    subtitles/           .srt / .vtt
    thumbnails/          covers, posters
    assets/              transcripts, image packs, data
    backups/             snapshots, manifests
```

## Security — what is stored, what is possible

- **Scope `drive.file`** — the agent can only see and manage files **it
  created itself**. Your other Drive content is invisible to it.
- `state/rclone/rclone.conf` holds the refresh token; it is chmod 600
  and never printed, never logged, never committed (`.gitignore`
  covers `state/`, `bin/`, `.tmp/`).
- The OAuth client is **rclone's published default** (open-source
  constants — client id and its obscure-encoded secret, derived from
  the binary at runtime and validated against Google's token endpoint).
  It is rate-limited and rclone plans to retire it during 2026; for
  heavy use, follow [rclone's guide](https://rclone.org/drive/#making-your-own-client-id)
  and put your own `client_id`/`client_secret` in
  `state/rclone/client.json`.
- Revoke any time: [myaccount.google.com](https://myaccount.google.com/)
  → Security → Third-party apps → rclone. The next `status` will say
  `AUTH_MISSING`; one fresh consent click restores it.

## Self-restoring internals

The sandbox this runs in can be wiped at any moment. agent2drive
rebuilds everything except the refresh token:

| Piece | Lost? | Recovery |
| --- | --- | --- |
| rclone binary | re-downloaded from downloads.rclone.org on any command |
| OAuth client | re-derived from the binary (public constants + documented AES-CTR "obscure" scheme) |
| `rclone.conf` (refresh token) | gone — but nothing on Drive is affected; one new consent click |
| Your Drive files | never affected; they live on Google's infrastructure |

## Testing

```bash
pip install cryptography pytest
python -m pytest tests/ -q     # no network, no Drive needed
```

The suite covers the obscure-reveal algorithm (fixed pair), pasted-URL
code parsing, consent-URL shape, and loud failures. Network-touching
paths (exchange, upload) are exercised for real by the maintainer
before each release.

## FAQ

**Why does the browser "fail" after I click Allow?**
It isn't failing — Google is redirecting to `127.0.0.1:53682`, an
address that only exists on *your* machine. Copy the address-bar URL;
that URL is the code carrier.

**Why paste-back instead of a redirect server?**
Because the agent runs headless in a sandbox. A redirect server would
mean tunnels, public endpoints and extra attack surface. A pasted URL
is zero infrastructure and the code is single-use with a ~10 minute TTL.

**Can I upload anything anywhere on my Drive?**
The script writes only inside `GDRIVE_ROOT/<slot>/<category>` and the
`drive.file` scope hides everything else. Point `GDRIVE_ROOT` somewhere
else if you prefer a different root folder name.

**Windows / macOS?**
The self-restore downloads the Linux build by default today; change
`RCLONE_ZIP` to your platform's zip and everything else works the same.

## License

MIT. rclone is MIT-licensed; its published OAuth constants are used and
credited here per its license.

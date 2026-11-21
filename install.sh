#!/bin/sh
# One-line bootstrap for humans and agents.
#   curl -fsSL https://raw.githubusercontent.com/Bilal140202/agent2drive/main/install.sh | sh
set -e

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[agent2drive] python3 is required" >&2
  exit 1
fi

install_pkg() {
  # Prefer a published release; fall back to the canonical GitHub source.
  "$PYTHON" -m pip install --user "$@" agent2drive 2>/dev/null || \
  "$PYTHON" -m pip install --user \
    "agent2drive @ git+https://github.com/Bilal140202/agent2drive.git@main"
}

if command -v pipx >/dev/null 2>&1; then
  pipx install agent2drive 2>/dev/null || \
    pipx install "git+https://github.com/Bilal140202/agent2drive.git@main"
else
  install_pkg || install_pkg --break-system-packages
fi

echo "[agent2drive] installed. Next:"
echo "  1. agent2drive url                # show the user the consent URL"
echo "  2. agent2drive connect --stdin    # paste the redirect URL you get back"
echo "  3. agent2drive init <slot>        # create the delivery slot"

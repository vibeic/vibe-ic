#!/usr/bin/env bash
# Install the gatekeeper required-status poller for THIS host and THIS user.
#
# The unit files carry no account name and no home directory (they used to
# carry one developer's, which is why they could only ever be installed on that
# developer's machine). The two machine-specific pieces are written here:
#
#   /etc/default/gatekeeper-poller                             GATEKEEPER_REPO_ROOT
#                                                              GATEKEEPER_STATE_DIR
#   /etc/systemd/system/gatekeeper-poller.service.d/10-local.conf   User=
#
# Usage:
#   sudo tools/ci/install_gatekeeper_poller.sh          # install and start
#   tools/ci/install_gatekeeper_poller.sh --print       # show what it WOULD
#                                                       # write; needs no root
set -euo pipefail

PRINT_ONLY=0
[ "${1:-}" = "--print" ] && PRINT_ONLY=1

# The user the poller runs as: the human behind `sudo`, not root. A poller
# running as root would use root's gh credentials, which are not the ones the
# gate is meant to speak with.
RUN_USER="${GATEKEEPER_RUN_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"
if [ "$RUN_USER" = "root" ]; then
    echo "REFUSED: refusing to run the poller as root -- it would use root's" >&2
    echo "gh credentials, not yours. Set GATEKEEPER_RUN_USER=<you>." >&2
    exit 2
fi

# The checkout to gate: derived from where this script lives, so it is right by
# construction rather than by a literal someone has to remember to update.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${GATEKEEPER_REPO_ROOT:-$(cd "$HERE/../.." && pwd)}"
if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "REFUSED: $REPO_ROOT is not a git checkout." >&2
    echo "Set GATEKEEPER_REPO_ROOT to the vibe-ic checkout to gate." >&2
    exit 2
fi
if [ ! -f "$REPO_ROOT/tools/ci/gatekeeper_status_poller.py" ]; then
    echo "REFUSED: $REPO_ROOT has no tools/ci/gatekeeper_status_poller.py." >&2
    exit 2
fi

RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
if [ -z "$RUN_HOME" ]; then
    echo "REFUSED: no such user: $RUN_USER" >&2
    exit 2
fi
STATE_DIR="${GATEKEEPER_STATE_DIR:-$RUN_HOME/.gatekeeper-poller}"

ENV_FILE="/etc/default/gatekeeper-poller"
DROPIN_DIR="/etc/systemd/system/gatekeeper-poller.service.d"

env_body() {
    cat <<ENVEOF
# Written by tools/ci/install_gatekeeper_poller.sh -- machine-specific.
GATEKEEPER_REPO_ROOT=$REPO_ROOT
GATEKEEPER_STATE_DIR=$STATE_DIR
ENVEOF
}
dropin_body() {
    cat <<DROPEOF
# Written by tools/ci/install_gatekeeper_poller.sh -- machine-specific.
[Service]
User=$RUN_USER
DROPEOF
}

if [ "$PRINT_ONLY" = 1 ]; then
    echo "=== $ENV_FILE ==="; env_body
    echo "=== $DROPIN_DIR/10-local.conf ==="; dropin_body
    exit 0
fi

[ "$(id -u)" = 0 ] || { echo "REFUSED: run this with sudo (or --print)." >&2; exit 2; }

env_body > "$ENV_FILE"
install -d "$DROPIN_DIR"
dropin_body > "$DROPIN_DIR/10-local.conf"
install -d -o "$RUN_USER" "$STATE_DIR"
install -m 0644 "$REPO_ROOT/tools/ci/gatekeeper-poller.service" \
                "$REPO_ROOT/tools/ci/gatekeeper-poller.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gatekeeper-poller.timer
systemctl list-timers gatekeeper-poller.timer --no-pager

#!/usr/bin/env bash
# gatekeeper_protect_main.sh — turn the required status check on (or off) for `main`.
#
# This is the half of the mechanism that makes an unchecked landing IMPOSSIBLE
# rather than merely discouraged. `tools/ci/gatekeeper_status_poller.py` decides
# the verdict; this decides that the verdict is REQUIRED.
#
# MEASURED, on throwaway branches, before this file existed (2026-08-12):
#
#   push a commit with no status  -> remote: error: GH006: Protected branch
#                                    update failed. Required status check
#                                    "vibe-ic/gatekeeper-land" is expected.
#                                                                    REJECTED
#   post the status, push same SHA ->                                 ACCEPTED
#
# The rejection happened to a repository ADMIN with enforce_admins=true. That is
# the difference between this and a convention.
#
# WHY enforce_admins=true. The identity that lands most is the one whose
# accidental unchecked push costs the most; an escape hatch reserved for that
# identity is the hole, not the mitigation.
#
# WHY strict=false. `strict:true` additionally demands the branch be up to date
# with base before merging, which on a fast-moving repo means re-running an
# eleven-minute gate after every unrelated landing. That is how an expensive
# gate becomes the thing people turn off. Correctness here comes from the status
# being bound to the exact SHA that gets pushed, not from recency.
#
# WHAT IT DOES NOT CLOSE. Anyone with write access can POST a green status by
# hand. This closes the ACCIDENT path completely — which is what produced
# `49 failed, 3871 passed` on an unwatched `main` — and turns the deliberate
# path into a single auditable API call. No plan-level control exists for that
# here, so it is stated rather than hidden.
#
# THE DIRECT-PUSH FLOW STILL WORKS (2026-06-26 owner directive). Because the
# required status is bound to a SHA, not to a pull request:
#
#     git push origin HEAD:refs/heads/land/$(git rev-parse --short HEAD)
#     tools/ci/gatekeeper_status_poller.py --sha $(git rev-parse HEAD)
#     git push origin $(git rev-parse HEAD):main      # accepted once green
#
# Usage:  tools/ci/gatekeeper_protect_main.sh {on|off|status}
set -uo pipefail

REPO="${GATEKEEPER_REPO:-vibeic/vibe-ic}"
BRANCH="${GATEKEEPER_BRANCH:-main}"
CONTEXT="${GATEKEEPER_CONTEXT:-vibe-ic/gatekeeper-land}"
ENC="${BRANCH//\//%2F}"

case "${1:-status}" in
  on)
    tmp="$(mktemp)"
    cat > "$tmp" <<JSON
{
  "required_status_checks": {"strict": false, "contexts": ["$CONTEXT"]},
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
    echo "enabling protection on $REPO@$BRANCH requiring '$CONTEXT'…"
    gh api -X PUT "repos/$REPO/branches/$ENC/protection" --input "$tmp" >/dev/null || {
      echo "FAILED to set protection" >&2; rm -f "$tmp"; exit 1; }
    rm -f "$tmp"
    echo "OK. From now on a push or merge to '$BRANCH' whose commit lacks a"
    echo "green '$CONTEXT' status is refused by GitHub itself."
    ;;
  off)
    # Deliberately loud: turning this off reopens all three unchecked paths.
    echo "REMOVING protection from $REPO@$BRANCH — this reopens unchecked landing." >&2
    gh api -X DELETE "repos/$REPO/branches/$ENC/protection" && echo "protection removed"
    ;;
  status)
    # NOTE: an unprotected branch answers 404 with a JSON *body*
    # (`{"message":"Branch not protected"}`), which parses perfectly well. A
    # reader that only checks "did JSON parse" reports `protected: yes` for a
    # wide-open branch — measured, on the first version of this script. So the
    # shape is inspected, not merely the parse.
    gh api "repos/$REPO/branches/$ENC/protection" 2>/dev/null \
      | python3 -c 'import sys,json
raw=sys.stdin.read().strip()
if not raw: print("NOT PROTECTED (no response)"); raise SystemExit(0)
try: d=json.loads(raw)
except Exception: print("NOT PROTECTED (unparseable response)"); raise SystemExit(0)
if not isinstance(d,dict) or "required_status_checks" not in d:
    print("NOT PROTECTED —", d.get("message","unknown") if isinstance(d,dict) else "unknown")
    raise SystemExit(0)
rsc=d.get("required_status_checks") or {}
print("protected:      yes")
print("required ctx:  ", rsc.get("contexts"))
print("strict:        ", rsc.get("strict"))
print("enforce_admins:", (d.get("enforce_admins") or {}).get("enabled"))'
    ;;
  *) echo "usage: $0 {on|off|status}" >&2; exit 2 ;;
esac

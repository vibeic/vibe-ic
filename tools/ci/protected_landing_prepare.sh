#!/usr/bin/env bash
# protected_landing_prepare.sh — the protected-tuple ceremony, in one command.
#
# WHY THIS EXISTS. Editing any of the 47 protected paths requires: author a
# manifest naming the moved paths and their future bytes, commit THAT ALONE
# (PREPARE), then install the bytes (ACTIVATE). Every step of that is right --
# the split is what makes `current` a state the repository actually had, and it
# is what caught five paths that had drifted onto main with no transition
# opened for them. What was wrong is that it was FOUR hand-run commands with a
# temp directory in the middle, so the cheap thing to do was to skip it.
#
# THIS REMOVES NO CHECK. It derives `--next-file` from the working tree instead
# of from the operator's memory, and it commits in the same two-commit shape by
# the same authoring program. `test_phase_b_activated_parity` is the judge
# either way and is run at the end; if it refuses, so does this.
#
# Usage:  tools/ci/protected_landing_prepare.sh <transition-id> [<current-id>]
#         with the edits already in the working tree.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)" || exit 2
cd "$ROOT" || exit 2
TID="${1:?usage: protected_landing_prepare.sh <transition-id> [<current-id>]}"
CID="${2:-live-at-$(git rev-parse --short=10 HEAD)}"
MANIFEST=tools/ci/protected_landing_transition.json

mapfile -t PROT < <(python3 -c "
import json,sys
print('\n'.join(r['path'] for r in json.load(open('$MANIFEST'))['paths']))")
mapfile -t DIRTY < <(git status --porcelain | sed 's/^...//')
MOVED=(); for p in "${DIRTY[@]}"; do for q in "${PROT[@]}"; do [ "$p" = "$q" ] && MOVED+=("$p"); done; done

if [ "${#MOVED[@]}" -eq 0 ]; then
  echo "protected_landing_prepare: no protected path is modified — nothing to prepare."
  echo "  (that is not a failure; commit normally.)"
  echo "  If a protected path DRIFTED — it ships bytes the register records in neither"
  echo "  state, because some landing moved it without opening a transition — there is"
  echo "  nothing to prepare and the repair is a RE-OBSERVATION, which records the tree"
  echo "  and authorises nothing:"
  echo "    python3 tools/ci/protected_landing_manifest_author.py --repo . \\"
  echo "      --commit HEAD --transition-id <id> --current-id <id-naming-the-mover> \\"
  echo "      --next-id <id>-next --no-move --out $MANIFEST"
  exit 0
fi
echo "protected_landing_prepare: ${#MOVED[@]} protected path(s) move:"
printf '    %s\n' "${MOVED[@]}"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
ARGS=(); for p in "${MOVED[@]}"; do
  f="$STAGE/$(printf '%s' "$p" | tr / _)"; cp "$p" "$f"; ARGS+=(--next-file "$p=$f")
  # FROM HEAD, NOT FROM THE INDEX. `git checkout -- <path>` restores the INDEX
  # copy, so an operator who had already `git add`ed the edit got a PREPARE that
  # CARRIED THE NEW BYTES -- the one thing the PREPARE half must never do. The
  # split exists so `current` is a state the repository actually had; a PREPARE
  # holding the future bytes describes a tree nobody ever ran. MEASURED here
  # while authoring `protected-path-may-be-renamed-v1`: with the edit staged,
  # the PREPARE commit was `protected_landing_transition.json | 2 +-` AND
  # `protected_landing_transition.py | 301 ++++`, and nothing said so.
  git checkout -q HEAD -- "$p" || exit 2
done

# THE EDITS ARE RESTORED ON EVERY EXIT, INCLUDING A REFUSAL.
# Between the restore above and the ACTIVATE half below, the ONLY copy of the
# operator's work is $STAGE -- and $STAGE is removed by the EXIT trap. MEASURED
# while authoring `protected-path-may-be-renamed-v1`: the author refused, this
# script exited, the trap fired, and a 301-line edit to a protected file was
# gone with no message about it. A ceremony that eats the change it exists to
# record is worse than no ceremony.
restore_edits() { local q; for q in "${MOVED[@]}"; do
  cp "$STAGE/$(printf '%s' "$q" | tr / _)" "$q"; done; }

python3 tools/ci/protected_landing_manifest_author.py --repo . --commit HEAD \
  --transition-id "$TID" --current-id "$CID" --next-id "$TID-next" \
  "${ARGS[@]}" --out "$MANIFEST" || {
    restore_edits
    git checkout -q HEAD -- "$MANIFEST" 2>/dev/null
    echo "  REFUSE: the manifest could not be authored"
    echo "  (your edits to the protected path(s) are back in the working tree)"
    exit 1; }

git add "$MANIFEST"
git commit -q --no-gpg-sign -m "landing(PREPARE): $TID — ${#MOVED[@]} protected path(s) move

$(printf '  %s\n' "${MOVED[@]}")

current is recorded from $(git rev-parse --short HEAD)'s own tree." || {
    restore_edits; exit 1; }
echo "  PREPARE  $(git rev-parse --short HEAD)"

restore_edits
echo "  bytes restored — commit them as the ACTIVATE half, then:"
echo "    python3 -I -B vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py \\"
echo "      -q tools/ci/test_phase_b_activated_parity.py"

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
  echo "  (that is not a failure; commit normally.)"; exit 0
fi
echo "protected_landing_prepare: ${#MOVED[@]} protected path(s) move:"
printf '    %s\n' "${MOVED[@]}"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
ARGS=(); for p in "${MOVED[@]}"; do
  f="$STAGE/$(printf '%s' "$p" | tr / _)"; cp "$p" "$f"; ARGS+=(--next-file "$p=$f")
  git checkout -q -- "$p" || exit 2
done

python3 tools/ci/protected_landing_manifest_author.py --repo . --commit HEAD \
  --transition-id "$TID" --current-id "$CID" --next-id "$TID-next" \
  "${ARGS[@]}" --out "$MANIFEST" || { echo "  REFUSE: the manifest could not be authored"; exit 1; }

git add "$MANIFEST"
git commit -q --no-gpg-sign -m "landing(PREPARE): $TID — ${#MOVED[@]} protected path(s) move

$(printf '  %s\n' "${MOVED[@]}")

current is recorded from $(git rev-parse --short HEAD)'s own tree." || exit 1
echo "  PREPARE  $(git rev-parse --short HEAD)"

for p in "${MOVED[@]}"; do cp "$STAGE/$(printf '%s' "$p" | tr / _)" "$p"; done
echo "  bytes restored — commit them as the ACTIVATE half, then:"
echo "    python3 -I -B vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py \\"
echo "      -q tools/ci/test_phase_b_activated_parity.py"

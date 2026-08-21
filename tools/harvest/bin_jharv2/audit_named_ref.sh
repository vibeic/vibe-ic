#!/usr/bin/env bash
# audit_named_ref.sh <verdicts.tsv> -- the STRICT check, per jharv3: a reader follows the ref the
# ROW NAMES, not the set of all rescue refs. "some harvest ref contains this sha" passes even when
# the row points somewhere the sha is not. Ask, for each row that claims preservation: does the ref
# THIS ROW NAMES contain the sha THIS ROW NAMES, as read from the remote?
set -uo pipefail
R=/home/reyerchu/vibe-ic
F="${1:?}"
ok=0; bad=0
while IFS= read -r line; do
  ev=${line#*$'\t'}; ev=${ev#*$'\t'}
  case "$ev" in *"IS preserved"*) ;; *) continue;; esac
  p=${line%%$'\t'*}
  # two wordings: "is a parent of <ref>" and "IS the tip of <ref>". An auditor that knows only
  # one of them reports the other as UNPARSEABLE, which reads exactly like a defect and is not.
  sha=$(printf '%s' "$ev" | sed -n 's/.*IS preserved: commit \([0-9a-f]\{7,\}\) \(is a parent of\|IS the tip of\) \([^ ]*\) .*/\1/p')
  ref=$(printf '%s' "$ev" | sed -n 's/.*IS preserved: commit \([0-9a-f]\{7,\}\) \(is a parent of\|IS the tip of\) \([^ ]*\) .*/\3/p')
  [ -n "$sha" ] && [ -n "$ref" ] || { echo "  UNPARSEABLE $p"; bad=$((bad+1)); continue; }
  full=$(git -C "$R" rev-parse -q --verify "refs/remotes/origin/$ref" 2>/dev/null)
  if [ -z "$full" ]; then echo "  REF_ABSENT $p -> $ref"; bad=$((bad+1)); continue; fi
  if [ "${full:0:${#sha}}" = "$sha" ]; then ok=$((ok+1)); continue; fi   # the ref IS the commit
  if git -C "$R" cat-file -p "$full" 2>/dev/null | awk '$1=="parent"{print $2}' | grep -q "^$sha"; then ok=$((ok+1))
  else echo "  **NOT IN THE REF IT NAMES** $p sha=$sha ref=$ref"; bad=$((bad+1)); fi
done < <(tail -n +2 "$F")
echo "$(basename "$F"): named-ref-correct=$ok wrong=$bad"

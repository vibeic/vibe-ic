#!/usr/bin/env bash
# mkmd.sh -- render rows.tsv into the report table, applying the uncommitted-state
# overrides that the committed-content pass cannot see.
set -uo pipefail
# Inputs default to the PERSISTENT copy, not the /tmp scratchpad a reboot clears. And a
# missing input must FAIL, not yield an empty file: a stage that emits nothing looks exactly
# like a stage that found nothing (this pipeline already shipped that bug once).
S=${S:-/home/reyerchu/_harv_priv}
need(){ [ -s "$1" ] || { echo "REFUSING: $(basename "$0") needs $1 and it is missing or empty" >&2; exit 2; }; }
need "$S/rows.tsv"
while IFS=$'\t' read -r v wt br head st nown ndiff nnovel nsuper f sa sb la lb desc; do
  note=""
  case "$wt" in
    /home/reyerchu/_v1123)
      v=KEEP; st=KEEP_UNCOMMITTED_STAGED_TREE
      note="HEAD is an ancestor of main and holds nothing, but the INDEX holds the whole tree of \`bd2a9a1c\` (= \`refs/pr/1123\`): 224 staged blobs differ from main and 17 paths are absent from main. Of PR-1123's own 5 files, all 5 differ from main by sha256 — e.g. \`tool_diagnostic_id_gate.py\` pr1123=\`1d9d24e3cb6e1549\` (752 lines) vs main=\`1f501b82ff6be19c\` (1102 lines). Main carries a LATER version of the same gate, so most of this is superseded — but it was never committed, so nothing here is recoverable from any ref if the tree goes."
      f="(staged) vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_gate.py"; sa=1d9d24e3cb6e1549; sb=1f501b82ff6be19c; la=752; lb=1102;;
    /home/reyerchu/_tim_priv/wt-jsetup-base)
      v=KEEP; st=KEEP_UNCOMMITTED_UNTRACKED
      note="Committed content matches main exactly (HEAD is an ancestor). Two UNTRACKED files sit on disk, both on paths that exist on main with different bytes: \`declared_clock_period.py\` and \`tests/test_declared_clock_period_table.py\`. Untracked means no commit, no branch, no ref — this is the most losable state in the shard."
      f="(untracked) vibe-ic-marketplace/plugins/vibe-ic/programs/declared_clock_period.py";;
    /tmp/regen_4e51c4853)
      v=KEEP; st=KEEP_UNCOMMITTED_MODIFIED
      note="Committed content matches main. One tracked file is modified on disk and differs from main: \`programs/tests/matrix/README.md\` (7 lines changed). Small, but it is not on main and not committed anywhere."
      f="(modified) vibe-ic-marketplace/plugins/vibe-ic/programs/tests/matrix/README.md";;
    /home/reyerchu/vibe-ic-shard)
      note="**Clone root, not a plain worktree** — its \`.git\` owns the 16 \`/tmp/shard_*\` and \`/tmp/regen_*\` worktrees below and their objects. Its committed content matches main, and its 21951 status lines are ALL \`D\`: the working files were deleted from disk, so there is nothing in the tree to recover. Dropping the *content* is right; deleting the *directory* would take the object store with it."
      st=DROP_ALL_FILES_MATCH_TREE_EMPTIED;;
    /home/reyerchu/vibe-ic)
      note="\`${f}\` sha256 \`${sa}\` (${la} lines) vs main \`${sb}\` (${lb} lines) — ${nnovel} of ${ndiff} differing files are novel. **Plus 141 untracked files on disk** (new \`programs/*.py\`, \`tools/ci/*\`, upstream assessments), committed nowhere."
      ;;
  esac
  if [ "$v" = KEEP ] && [ -z "$note" ]; then
    if [ "$sa" = DELETED_BY_BRANCH ]; then
      note="\`${f}\` is **deleted by this branch** and still present on main (main sha256 \`${sb}\`, ${lb} lines) — the removal is the content that is not on main."
    elif [ "$sb" = ABSENT_ON_MAIN ]; then
      note="\`${f}\` is **absent from main entirely** (sha256 \`${sa}\`, ${la} lines). ${desc%%|*}"
    else
      note="\`${f}\` sha256 \`${sa}\` (${la} lines) vs main \`${sb}\` (${lb} lines). ${desc%%|*}"
    fi
    [ "$st" = KEEP_SUPERSEDED_CONTENT_DIFFERS ] && note="$note — but every one of its ${nsuper} differing files reverse-applies onto main, so the work looks already landed and only main's later drift remains. Kept because the bytes differ; a wrong DROP is unrecoverable."
    [ "$nsuper" != "0" ] && [ "$st" = KEEP_NOVEL_CONTENT ] && note="$note (${nnovel} of ${ndiff} differing files are novel; ${nsuper} already reverse-apply onto main.)"
  fi
  [ "$v" = DROP ] && [ -z "$note" ] && {
    if [ "$nown" = "0" ]; then
      note="Branch touched no file relative to main; every path in its tree that it owns is byte-identical to \`origin/main\`. Nothing in it is not on main."
    else
      note="Branch touched ${nown} files and **all ${nown} are byte-identical to \`origin/main\`** — the squash case: it still reads as \"ahead\", and its content is entirely landed."
    fi
  }
  printf '| `%s` | **%s** | `%s` | %s |\n' "$wt" "$v" "$st" "$note"
done < <(awk -F'\t' -v OFS='\t' '{for(i=1;i<=NF;i++) if($i=="") $i="-"; print}' "$S/rows.tsv")

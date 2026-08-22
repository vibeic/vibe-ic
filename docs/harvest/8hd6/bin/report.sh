#!/usr/bin/env bash
# report.sh -- turn the judged TSVs into the per-worktree evidence lines.
set -uo pipefail
# Inputs default to the PERSISTENT copy, not the /tmp scratchpad a reboot clears. And a
# missing input must FAIL, not yield an empty file: a stage that emits nothing looks exactly
# like a stage that found nothing (this pipeline already shipped that bug once).
S=${S:-/home/reyerchu/_harv_priv}
need(){ [ -s "$1" ] || { echo "REFUSING: $(basename "$0") needs $1 and it is missing or empty" >&2; exit 2; }; }
need "$S/all.tsv"
cat "$S"/all.tsv | awk -F'\t' -v OFS='\t' '{for(i=1;i<=NF;i++) if($i=="") $i="-"; print}' | while IFS=$'\t' read -r repo wt br head st nown ndiff nnovel nsuper nnoise trk unt novel super subj meta; do
  case "$st" in
    KEEP_*)
      # Prefer, as the named example, a path that main does not have AT ALL -- that is the
      # least arguable KEEP evidence there is. Failing that prefer a real source file over
      # an INDEX/README, which differ in almost every branch and say least about the work.
      f=""; best=""; anypresent=""; stale=""
      IFS=',' read -ra cand <<< "$novel,$super"
      for c in "${cand[@]}"; do
        [ -n "$c" ] && [ "$c" != "-" ] || continue
        git -C "$repo" rev-parse -q --verify "$head:$c" >/dev/null 2>&1 || continue
        if ! git -C "$repo" rev-parse -q --verify "origin/main:$c" >/dev/null 2>&1; then
          # "absent from main" is only strong evidence if main NEVER had the path. If main
          # DELETED it, the branch merely predates the removal -- that is stale content, not
          # new work, and naming it as the example overstates the KEEP.
          if git -C "$repo" log --diff-filter=D --format=%h -1 origin/main -- "$c" 2>/dev/null | grep -q .; then
            [ -z "$stale" ] && stale=$c; continue
          fi
          f=$c; break
        fi
        [ -z "$anypresent" ] && anypresent=$c
        case "$c" in */INDEX.md|*/README.md|*.md) ;; *) [ -z "$best" ] && best=$c;; esac
      done
      [ -n "$f" ] || f=$best
      [ -n "$f" ] || f=$anypresent
      [ -n "$f" ] || f=$stale
      if [ -n "$f" ]; then
        IFS=$'\t' read -r sa sb la lb desc < <(bash "$(dirname "$0")/evidence.sh" "$repo" "$head" "$f")
        printf 'KEEP\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
          "$wt" "$br" "${head:0:9}" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$f" "$sa" "$sb" "$la" "$lb" "$desc|$subj"
      else
        printf 'KEEP\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t-\t-\t-\t-\t-\t%s\n' \
          "$wt" "$br" "${head:0:9}" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$subj"
      fi;;
    DROP_*)
      printf 'DROP\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t-\t-\t-\t-\t-\t%s\n' \
        "$wt" "$br" "${head:0:9}" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$subj";;
    *)
      printf 'UNDETERMINED\t%s\t%s\t%s\t%s\t-\t-\t-\t-\t-\t-\t-\t-\t-\t%s\n' \
        "$wt" "$br" "${head:0:9}" "$st" "$subj";;
  esac
done

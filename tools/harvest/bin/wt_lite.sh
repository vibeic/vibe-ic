#!/usr/bin/env bash
# wt_lite.sh <repo> -- the cheap classification path: ONE numstat per worktree, no
# per-file apply test. Used for clones whose own origin/main is weeks stale, where
# the per-file tier-2 loop costs 18k invocations per worktree and answers nothing
# (see findings F26).
# TSV: repo path branch head LITE nfiles 0 0 nadd ndel code_add trk unt subject topdirs "" cdate mainref
set -uo pipefail
REPO="${1:?}"; cd "$REPO" || exit 1
MAIN=""; for c in origin/main main origin/master; do git rev-parse --verify -q "$c" >/dev/null 2>&1 && { MAIN=$c; break; }; done
[ -n "$MAIN" ] || { echo "NOMAIN $REPO" >&2; exit 2; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
git worktree list --porcelain | awk '
  /^worktree /{p=substr($0,10)} /^HEAD /{h=substr($0,6)}
  /^branch /{b=substr($0,8)} /^detached/{b="(detached)"}
  /^$/{if(p!=""){print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h);p="";b="";h=""}}
  END{if(p!="")print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h)}' \
| while IFS=$'\t' read -r wt br head; do
  br=${br#refs/heads/}
  [ "$head" = "-" ] && continue
  subj=$(git log -1 --format='%s' "$head" 2>/dev/null | tr '\t|' '  ' | cut -c1-160)
  cdate=$(git log -1 --format='%cs' "$head" 2>/dev/null)
  mb=$(git merge-base "$head" "$MAIN" 2>/dev/null) || mb=""
  [ -n "$mb" ] || continue
  git diff --name-only "$mb" "$head" 2>/dev/null > "$T/own" || true
  n=$(grep -c '' < "$T/own")
  read -r nadd ndel cadd < <(git diff --numstat "$MAIN" "$head" 2>/dev/null | awk -v OWN="$T/own" '
    BEGIN{while((getline l < OWN)>0) own[l]=1}
    { f=$3; if(!(f in own))next; a=($1=="-"?0:$1); d=($2=="-"?0:$2); ta+=a; td+=d
      gen=(f ~ /^benchmark-data\//)||(f ~ /\.(json|html|csv|svg|lock|log|gds|def|lef|sdf|spef)$/)||(f ~ /(^|\/)(reports?|runs?|logs?|out|output|results?)\//)
      if(!gen&&a>0) ca+=a }
    END{printf "%d %d %d", ta+0, td+0, ca+0}')
  trk=$(git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '^[MARC]')
  unt=$(git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??')
  td=$(cut -d/ -f1-2 < "$T/own" | sort -u | head -6 | paste -sd, -)
  printf '%s\t%s\t%s\t%s\tLITE\t%s\t0\t0\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t\t%s\t%s\n' \
    "$REPO" "$wt" "$br" "$head" "$n" "${nadd:-0}" "${ndel:-0}" "${cadd:-0}" "${trk:-0}" "${unt:-0}" "$subj" "$td" "$cdate" "$MAIN"
done

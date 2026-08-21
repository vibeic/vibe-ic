#!/usr/bin/env bash
# wt_full.sh <repo> -- every measurement this triage needs, in ONE pass per worktree.
# TSV: repo path branch head state nfiles ndiffer nnovel nadd ndel code_add trk unt
#      subject topdirs novelfiles cdate mainref
# READ-ONLY. Tier-2 uses a temp index so no worktree/checkout is created.
set -uo pipefail
REPO="${1:?}"; cd "$REPO" || exit 1
MAIN=""
for c in origin/main main origin/master; do
  git rev-parse --verify -q "$c" >/dev/null 2>&1 && { MAIN=$c; break; }
done
[ -n "$MAIN" ] || { echo "NOMAIN $REPO" >&2; exit 2; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_INDEX_FILE="$T/idx"; git read-tree "$MAIN" 2>/dev/null || exit 3
git diff "$MAIN~1" "$MAIN" > "$T/ctl" 2>/dev/null
[ -s "$T/ctl" ] && ! git apply --cached --check -R "$T/ctl" 2>/dev/null && { echo "SELFTEST_FAIL $REPO" >&2; exit 4; }
isnoise(){ case "$1" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;; esac; return 1; }
git worktree list --porcelain | awk '
  /^worktree /{p=substr($0,10)} /^HEAD /{h=substr($0,6)}
  /^branch /{b=substr($0,8)} /^detached/{b="(detached)"}
  /^$/{if(p!=""){print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h);p="";b="";h=""}}
  END{if(p!="")print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h)}' \
| while IFS=$'\t' read -r wt br head; do
  br=${br#refs/heads/}
  # A missing DIRECTORY is not missing WORK: the commit is still in the object
  # store and reachable through this worktree's HEAD, and `git diff <mb> <head>`
  # needs no working tree. Classify it from the commit and FLAG the directory,
  # rather than emitting zeros -- zeros made nadd==0 and the engine called a
  # deleted tree "already in main, safe to delete" (findings F34).
  if [ -d "$wt" ]; then wtdir=present; else wtdir=REMOVED; fi
  [ "$head" = "-" ] && { printf '%s\t%s\t%s\t%s\tNOHEAD\t0\t0\t0\t0\t0\t0\t0\t0\t\t\t\t\t%s\t%s\n' "$REPO" "$wt" "$br" "$head" "$MAIN" "$wtdir"; continue; }
  subj=$(git log -1 --format='%s' "$head" 2>/dev/null | tr '\t|' '  ' | cut -c1-160)
  cdate=$(git log -1 --format='%cs' "$head" 2>/dev/null)
  mb=$(git merge-base "$head" "$MAIN" 2>/dev/null)
  [ -n "$mb" ] || { printf '%s\t%s\t%s\t%s\tNOMERGEBASE\t0\t0\t0\t0\t0\t0\t0\t0\t%s\t\t\t%s\t%s\t%s\n' "$REPO" "$wt" "$br" "$head" "$subj" "$cdate" "$MAIN" "$wtdir"; continue; }
  git diff --name-only "$mb" "$head" 2>/dev/null > "$T/own" || true
  n=$(grep -c '' < "$T/own"); differ=0; novel=0; nlist=""; vern=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    a=$(git rev-parse -q --verify "$head:$f" 2>/dev/null); b=$(git rev-parse -q --verify "$MAIN:$f" 2>/dev/null)
    [ "$a" = "$b" ] && continue
    differ=$((differ+1)); isnoise "$f" && { vern=$((vern+1)); continue; }
    git diff "$mb" "$head" -- "$f" > "$T/f" 2>/dev/null
    [ -s "$T/f" ] && git apply --cached --check -R "$T/f" 2>/dev/null && continue
    novel=$((novel+1)); [ ${#nlist} -lt 400 ] && nlist="${nlist}${nlist:+,}${f}"
  done < "$T/own"
  read -r nadd ndel cadd < <(git diff --numstat "$MAIN" "$head" 2>/dev/null | awk -v OWN="$T/own" '
     BEGIN{while((getline l < OWN)>0) own[l]=1}
     { f=$3; if(!(f in own))next; a=($1=="-"?0:$1); d=($2=="-"?0:$2); ta+=a; td+=d
       gen=(f ~ /^benchmark-data\//)||(f ~ /\.(json|html|csv|svg|lock|log|gds|def|lef|sdf|spef)$/)||(f ~ /(^|\/)(reports?|runs?|logs?|out|output|results?)\//)
       if(!gen&&a>0) ca+=a }
     END{printf "%d %d %d", ta+0, td+0, ca+0}')
  if   [ "$differ" -eq 0 ]; then st=LANDED_FILE
  elif [ "$novel" -eq 0 ] && [ "$vern" -gt 0 ]; then st=LANDED_VERONLY
  elif [ "$novel" -eq 0 ]; then st=LANDED_PATCH
  else st=UNLANDED; fi
  if [ "$wtdir" = present ]; then
    trk=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '')
    unt=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??')
  else trk=0; unt=0; fi
  td=$(cut -d/ -f1-2 < "$T/own" | sort -u | head -6 | paste -sd, -)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$REPO" "$wt" "$br" "$head" "$st" "$n" "$differ" "$novel" "${nadd:-0}" "${ndel:-0}" "${cadd:-0}" \
    "${trk:-0}" "${unt:-0}" "$subj" "$td" "$nlist" "$cdate" "$MAIN" "$wtdir"
done

#!/usr/bin/env bash
# wt_codeadd.sh <repo> [main-ref] -- split each worktree's nadd into AUTHORED code
# and GENERATED data.  TSV: path  nadd  ndel  nfiles  code_add  code_files
#
# nadd alone misleads: one tree scored 88225 added lines, of which 83144 were a
# single regenerated corpus_baseline.json. Recoverable ENGINEERING is the code
# half; a regenerated artefact can be produced again from the code.
# GENERATED := anything under benchmark-data/ , any .json/.html/.csv/.svg/.lock,
#              and report/log artefacts.
set -uo pipefail
cd "${1:?}" || exit 1
MAIN="${2:-origin/main}"
git worktree list --porcelain | awk '
  /^worktree /{p=substr($0,10)} /^HEAD /{h=substr($0,6)}
  /^$/{if(p!=""){print p"\t"(h==""?"-":h); p="";h=""}}
  END{if(p!="")print p"\t"(h==""?"-":h)}' | while IFS=$'\t' read -r wt head; do
  [ "$head" = "-" ] && { printf '%s\t0\t0\t0\t0\t0\n' "$wt"; continue; }
  mb=$(git merge-base "$head" "$MAIN" 2>/dev/null)
  [ -n "$mb" ] || { printf '%s\t0\t0\t0\t0\t0\n' "$wt"; continue; }
  own=$(mktemp)
  git diff --name-only "$mb" "$head" 2>/dev/null > "$own" || true
  git diff --numstat "$MAIN" "$head" 2>/dev/null | awk -v OWN="$own" -v W="$wt" '
    BEGIN{while((getline l < OWN)>0) own[l]=1}
    { f=$3; if(!(f in own)) next
      a=($1=="-"?0:$1); d=($2=="-"?0:$2); ta+=a; td+=d; n++
      gen = (f ~ /^benchmark-data\// ) || (f ~ /\.(json|html|csv|svg|lock|log|gds|def|lef|sdf|spef)$/) \
            || (f ~ /(^|\/)(reports?|runs?|logs?|out|output|results?)\//)
      if(!gen && a>0){ ca+=a; cf++ } }
    END{printf "%s\t%d\t%d\t%d\t%d\t%d\n", W, ta+0, td+0, n+0, ca+0, cf+0}'
  rm -f "$own"
done

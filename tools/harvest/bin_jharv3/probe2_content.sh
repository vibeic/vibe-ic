#!/bin/bash
# Read-only second pass: object existence, tree, merge-base, owned set vs main,
# ignored-file accounting, clone-wide stashes. Writes nothing.
export GIT_PAGER=cat GIT_TERMINAL_PROMPT=0
for p in "$@"; do
  [ -z "$p" ] && continue
  echo "=== PATH $p"
  if [ ! -d "$p" ]; then echo "ABSENT"; echo "ENDPATH"; continue; fi
  cd "$p" 2>/dev/null || { echo "NOCD"; echo "ENDPATH"; continue; }
  H=$(git rev-parse HEAD 2>/dev/null)
  echo "HEAD $H"
  if git cat-file -e "${H}^{commit}" 2>/dev/null; then echo "HEADOBJ present"; else echo "HEADOBJ MISSING_FROM_OBJECT_STORE"; fi
  echo "TREE $(git rev-parse 'HEAD^{tree}' 2>&1 | head -1)"
  M=$(git rev-parse origin/main 2>/dev/null); echo "MAIN $M"
  MB=$(git merge-base origin/main HEAD 2>/dev/null)
  if [ -z "$MB" ]; then echo "MERGEBASE NONE"; else echo "MERGEBASE $MB"; fi
  if [ -n "$MB" ]; then
    OW=$(git diff --name-only "$MB" HEAD 2>/dev/null)
    n=$(printf '%s' "$OW" | grep -c . )
    echo "OWNED $n"
    d=0
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      a=$(git rev-parse "HEAD:$f" 2>/dev/null || echo NONE)
      b=$(git rev-parse "origin/main:$f" 2>/dev/null || echo NONE)
      if [ "$a" != "$b" ]; then d=$((d+1)); echo "OWNDIFF $f head=$a main=$b"; fi
    done <<< "$OW"
    echo "OWNEDDIFFERING $d"
  fi
  ni=$(git status --porcelain --untracked-files=all --ignored=matching -z 2>/dev/null | tr '\0' '\n' | grep -c '^!! ')
  echo "IGNORED_ENTRIES $ni"
  git status --porcelain --untracked-files=all --ignored=matching -z 2>/dev/null | tr '\0' '\n' | grep '^!! ' | sed 's|^!! ||' | awk -F/ '{print $1}' | sort -u | head -20 | sed 's/^/IGNORED_TOP /'
  echo "STASHES $(git stash list 2>/dev/null | wc -l)"
  echo "ENDPATH"
  cd / 2>/dev/null
done

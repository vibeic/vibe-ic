#!/bin/bash
# Read-only third pass: name every ignored entry and every stash. Writes nothing.
export GIT_PAGER=cat GIT_TERMINAL_PROMPT=0
for p in "$@"; do
  [ -z "$p" ] && continue
  echo "=== PATH $p"
  cd "$p" 2>/dev/null || { echo "NOCD"; echo "ENDPATH"; continue; }
  echo "COMMONDIR $(git rev-parse --git-common-dir 2>&1 | head -1)"
  git status --porcelain --untracked-files=all --ignored=matching -z 2>/dev/null \
    | tr '\0' '\n' | grep '^!! ' | sed 's|^!! ||' | while IFS= read -r f; do
      if [ -f "$f" ]; then
        echo "IGN $(sha256sum -- "$f" | cut -d' ' -f1 | cut -c1-16) $(stat -c%s -- "$f") $f"
      elif [ -d "$f" ]; then
        echo "IGNDIR $(find "$f" -type f 2>/dev/null | wc -l) files $(du -sb "$f" 2>/dev/null | cut -f1) bytes $f"
      else
        echo "IGNOTHER $f"
      fi
    done
  git stash list --format='STASH %H %gd %s' 2>/dev/null
  echo "ENDPATH"
  cd / 2>/dev/null
done

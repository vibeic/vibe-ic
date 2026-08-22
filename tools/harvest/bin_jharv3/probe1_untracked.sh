#!/bin/bash
# Read-only. Reports untracked-ALL and tracked-modified content for each path given
# on stdin (one per line). Writes nothing anywhere.
export GIT_PAGER=cat GIT_TERMINAL_PROMPT=0
for p in "$@"; do
  [ -z "$p" ] && continue
  echo "=== PATH $p"
  if [ ! -d "$p" ]; then echo "ABSENT"; echo "ENDPATH"; continue; fi
  cd "$p" 2>/dev/null || { echo "NOCD"; echo "ENDPATH"; continue; }
  echo "HEAD $(git rev-parse HEAD 2>&1 | head -1)"
  echo "TOP $(git rev-parse --show-toplevel 2>&1 | head -1)"
  echo "COMMONDIR $(git rev-parse --git-common-dir 2>&1 | head -1)"
  echo "ORIGINMAIN $(git rev-parse origin/main 2>&1 | head -1)"
  n_unt=0; n_mod=0
  while IFS= read -r -d '' line; do
    st="${line:0:2}"; f="${line:3}"
    if [ "$st" = "??" ]; then
      n_unt=$((n_unt+1))
      if [ -f "$f" ]; then
        echo "UNT $(sha256sum -- "$f" | cut -d' ' -f1) $(stat -c%s -- "$f") $f"
      else
        echo "UNT - - $f (not a regular file)"
      fi
    else
      n_mod=$((n_mod+1))
      if [ -f "$f" ]; then
        echo "MOD [$st] $(sha256sum -- "$f" | cut -d' ' -f1) $(stat -c%s -- "$f") $f"
      else
        echo "MOD [$st] - - $f"
      fi
    fi
  done < <(git status --porcelain --untracked-files=all -z 2>/dev/null)
  echo "COUNTS untracked=$n_unt modified=$n_mod"
  echo "ENDPATH"
  cd / 2>/dev/null
done

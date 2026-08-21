#!/usr/bin/env bash
# find_checkouts.sh -- every git repository on this host, from the FILESYSTEM.
#
# Two things this must catch that the obvious method does not:
#  1. `git worktree list` reports only REGISTERED worktrees. A checkout whose registration
#     was pruned still holds its commits and its files. On this host 14 such checkouts
#     existed, 12 of them holding work not on main.
#  2. A BARE clone has no ".git" to find -- the repository IS the git dir -- so `-name .git`
#     misses it entirely, along with any worktree it owns. Detect it structurally instead.
set -uo pipefail
# (1) ordinary checkouts, every local filesystem
{ find / -xdev \( -path /proc -o -path /sys -o -path /snap -o -path /var/lib/docker \) -prune \
       -o -name '.git' -print 2>/dev/null
  for m in $(df -T -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | awk 'NR>1{print $NF}'); do
    [ "$m" = / ] && continue
    find "$m" -xdev -name '.git' -print 2>/dev/null
  done
} | sed 's#/\.git$##'
# (2) bare clones: a dir holding HEAD + objects/ + refs/ whose own name is not ".git"
find / -xdev \( -path /proc -o -path /sys -o -path /snap \) -prune -o -name HEAD -type f -print 2>/dev/null \
 | sed 's#/HEAD$##' | grep -v '/\.git$' | grep -v '/\.git/' | while read -r d; do
     [ -d "$d/objects" ] && [ -d "$d/refs" ] || continue
     [ "$(git -C "$d" rev-parse --is-bare-repository 2>/dev/null)" = true ] && echo "$d"
   done

#!/bin/bash
# Build the (path,blob) map of EVERY pair origin/main's history ever held.
# One pass, no pathspec: the per-path form does not scale (proving one worktree
# needed 17736 pathspecs and did not complete). ~39k pairs, under a minute.
# -m includes merge-expressed history; both pre- and post-image blobs are kept,
# because a blob main later DELETED is still content main held at that path.
MAIN=${MAIN:-a4caccefe}; OUT=${1:?usage: build_main_pathblob.sh <out.tsv>}
cd "$(git rev-parse --show-toplevel)"
git log --format= --raw --no-abbrev --no-renames -m $MAIN 2>/dev/null \
 | awk -f "$(dirname "$0")/main_pathblob.awk" | LC_ALL=C sort -u > "$OUT"
echo "$(wc -l < "$OUT") (path,blob) pairs"

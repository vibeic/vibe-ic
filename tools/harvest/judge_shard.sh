#!/usr/bin/env bash
# judge_shard.sh <shard.tsv> <out.tsv> [start] [count]
#
# Emits the deliverable contract: path<TAB>verdict<TAB>evidence
# verdict in {RECOVER, ABANDON, LANDED, UNREACHABLE}
#
# CONTENT ONLY. vibe-ic squash-lands, so a branch whose content is entirely on main
# is still not an ancestor of it: merge-base --is-ancestor / branch --merged /
# rev-list origin/main..HEAD / git status all call landed work unlanded. Nothing
# here reads any of them.
#
# Files are compared by hash of their CONTENT as recorded in the commit
# (`git show <rev>:<path>`), never by the working tree -- 24 worktrees on this fleet
# have had their directory deleted while the commit survives, and those are exactly
# the ones a working-tree comparison would silently mis-read.
# Git blob ids are themselves content hashes, so they are used for the sweep; the
# sha256 the contract asks for is computed for the file actually named as evidence.
set -uo pipefail
SHARD="${1:?}"; OUT="${2:?}"; START="${3:-1}"; COUNT="${4:-100000}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# e3b0c442... is sha256 of EMPTY input. `git show` on a path that does not exist in
# a rev prints nothing and exits nonzero, so piping it blind reports that constant
# and reads as "a real file that happens to differ". Check existence first.
sha_of(){ git -C "$1" rev-parse -q --verify "$2:$3" >/dev/null 2>&1 || { echo "ABSENT"; return; }
          git -C "$1" show "$2:$3" 2>/dev/null | sha256sum | cut -c1-16; }

tail -n+2 "$SHARD" | sed -n "${START},$((START+COUNT-1))p" | while IFS=$'\t' read -r host wt repo head br kind prior notes; do
  [ -n "$wt" ] || continue
  if [ ! -d "$repo" ]; then
    printf '%s\tUNREACHABLE\tclone %s is gone from this host; worktree not readable\n' "$wt" "$repo" >> "$OUT"; continue
  fi
  MAIN=$(git -C "$repo" rev-parse --short origin/main 2>/dev/null)
  if [ -z "$MAIN" ]; then
    printf '%s\tUNREACHABLE\tclone %s has no origin/main ref\n' "$wt" "$repo" >> "$OUT"; continue
  fi
  # HEAD is re-read from the worktree registration, never trusted from the shard file
  h=$(git -C "$repo" rev-parse -q --verify "$head" 2>/dev/null)
  if [ -z "$h" ]; then
    printf '%s\tUNREACHABLE\tcommit %s not present in %s\n' "$wt" "${head:0:9}" "$repo" >> "$OUT"; continue
  fi
  subj=$(git -C "$repo" log -1 --format='%s' "$h" 2>/dev/null | tr '\t|' '  ' | cut -c1-90)
  mb=$(git -C "$repo" merge-base "$h" origin/main 2>/dev/null)
  if [ -z "$mb" ]; then
    printf '%s\tRECOVER\tno merge-base with main %s, so its content cannot be shown to be on main; keeping. tip: %s\n' "$wt" "$MAIN" "$subj" >> "$OUT"; continue
  fi

  git -C "$repo" diff --name-only "$mb" "$h" 2>/dev/null > "$T/own"
  nfiles=$(grep -c '' < "$T/own")
  # ONE numstat, intersected with the files this tree itself touched.
  # git lists a file in `diff A B` exactly when its content hashes differ, so this
  # IS the per-file content comparison -- done in one pass instead of 2N processes.
  # col1 = lines the TREE has that main lacks (nadd, the only recoverable work);
  # col2 = lines MAIN has that the tree lacks (ndel, staleness, never work).
  eval "$(git -C "$repo" diff --numstat origin/main "$h" 2>/dev/null | awk -v OWN="$T/own" '
    BEGIN{while((getline l < OWN)>0) own[l]=1}
    { f=$3; if(!(f in own)) next
      differ++; if($1!="-")a+=$1; if($2!="-")d+=$2
      if (f ~ /(\.claude-plugin\/plugin\.json|marketplace\.json|\/VERSION$|^VERSION$|CHANGELOG\.md)$/) { if(weak=="") weak=f }
      else if (first=="") first=f }
    END{printf "differ=%d; nadd=%d; ndel=%d; first=%s; weak=%s", differ+0, a+0, d+0,
               (first==""?"\"\"":"\""first"\""), (weak==""?"\"\"":"\""weak"\"")}')"
  differ=${differ:-0}; nadd=${nadd:-0}; ndel=${ndel:-0}; first=${first:-}; weak=${weak:-}

  trk=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '^[MARC]')
  untr=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null | grep -c '^??')
  dgone=0; [ -d "$wt" ] || dgone=1

  # L2 FIRST. An uncommitted edit is held by no commit and exists on one disk, so it
  # outranks every landed-ness argument. This check used to sit BELOW the two LANDED
  # branches, which let four trees carrying uncommitted work be marked LANDED --
  # the verdict that says "safe to delete". The rule file always said L2 outranks
  # everything; the code did not.
  # Refinement, measured: "a tracked file is modified" is not the same as "this disk
  # holds bytes nothing else has". _wt_1390pg has one uncommitted edit that ADDS 0
  # lines and lacks 82 main has -- a stale copy, so deleting it loses nothing, and
  # flagging it RECOVER would be over-cautious. What matters is whether the disk side
  # ADDS lines main does not have, or carries untracked files.
  # (Residual, accepted: an uncommitted pure DELETION loses the intent to delete,
  # never any bytes -- main still holds them.)
  uadd=0
  if [ "${trk:-0}" -gt 0 ]; then
    for _f in $(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | awk '$1 ~ /^[MARC]/{print $2}'); do
      if git -C "$repo" cat-file -e "origin/main:$_f" 2>/dev/null; then
        _a=$(env -u GIT_INDEX_FILE git -C "$wt" diff --numstat origin/main -- "$_f" 2>/dev/null | awk '{print ($1=="-"?0:$1)}' | head -1)
      else _a=$(grep -c '' "$wt/$_f" 2>/dev/null || echo 0); fi   # main never held it
      uadd=$((uadd + ${_a:-0}))
    done
  fi
  if [ "${uadd:-0}" -gt 0 ] || [ "${untr:-0}" -gt 0 ]; then
    printf '%s\tRECOVER\tuncommitted work on one disk only: %s tracked file(s) modified adding %s line(s) main does not have, plus %s untracked file(s); held by no commit, so this outranks any landed-ness of the committed content. tip: %s\n' \
      "$wt" "${trk:-0}" "${uadd:-0}" "${untr:-0}" "$subj" >> "$OUT"; continue
  fi
  if [ "$nfiles" -eq 0 ] || [ "$differ" -eq 0 ]; then
    printf '%s\tLANDED\tall %s file(s) this tree changed hash-match main %s byte for byte (git blob ids equal for every one); nothing in it is absent from main. tip: %s\n' \
      "$wt" "$nfiles" "$MAIN" "$subj" >> "$OUT"; continue
  fi
  if [ "${nadd:-0}" -eq 0 ]; then
    printf '%s\tLANDED\t%s file(s) differ textually but the tree holds 0 lines main %s lacks (it is %s lines BEHIND main); every line it has is present there. tip: %s\n' \
      "$wt" "$differ" "$MAIN" "${ndel:-0}" "$subj" >> "$OUT"; continue
  fi

  [ -n "$first" ] || first="$weak"
  sh_a=$(sha_of "$repo" "$h" "$first"); sh_b=$(sha_of "$repo" "origin/main" "$first")
  if [ "$sh_b" = ABSENT ]; then base="$first: sha256 $sh_a in this tree, FILE ABSENT from main $MAIN"
  elif [ "$sh_a" = ABSENT ]; then base="$first: DELETED in this tree, sha256 $sh_b on main $MAIN"
  else base="$first: sha256 $sh_a in this tree vs $sh_b on main $MAIN"; fi

  if [ "$trk" -gt 0 ]; then
    printf '%s\tRECOVER\t%s; plus %s tracked file(s) uncommitted here and nowhere in git. %s lines absent from main across %s file(s). tip: %s\n' \
      "$wt" "$base" "$trk" "$nadd" "$differ" "$subj" >> "$OUT"; continue
  fi
  if [ "$dgone" -eq 1 ]; then
    printf '%s\tRECOVER\t%s; %s lines absent from main. WORKTREE DIRECTORY DELETED - commit survives in the object store, so recover the REF not the directory; do not git worktree prune. tip: %s\n' \
      "$wt" "$base" "$nadd" "$subj" >> "$OUT"; continue
  fi
  printf '%s\tRECOVER\t%s; %s lines across %s file(s) absent from main (%s lines behind). tip: %s\n' \
    "$wt" "$base" "$nadd" "$differ" "${ndel:-0}" "$subj" >> "$OUT"
done

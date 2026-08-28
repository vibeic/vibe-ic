# FINDING — the union of the seven patches is ALREADY ON LIVE MAIN

live main : 25196aa72717f8e696638d3c06c663a53a4e8623  (v1.12.28)
TREE_SHA  : edaef1f5418b74ea50b386b439bd53e3be6c9b83
clone     : /tmp/wpr2 on 8HD-9, fresh from https://github.com/vibeic/vibe-ic.git

## Instrument
Per-hunk reverse-apply is creation-hunk-unsafe (a file CREATED by patch N and then
revised by patch N+1 can never reverse-apply as a whole).  So the adjudicating
instrument is a LINE-SET test: every line a patch ADDS is looked for anywhere in
live main's version of that same file (blank lines ignored).
  script: /tmp/wpr2-art/residue_lines.py   output: /tmp/wpr2-art/02_residue_lines.txt

## Result: 1394 added lines across the seven; 23 absent from main.
  740147ae  241 added,   0 absent  FULLY LANDED
  b742c9b5  207 added,  14 absent  superseded (see below)
  395c9503  193 added,   0 absent  FULLY LANDED
  1b599dee  119 added,   0 absent  FULLY LANDED
  8206f4d0  303 added,   0 absent  FULLY LANDED
  f9f6d12a   51 added,   0 absent  FULLY LANDED
  02dc2f03  280 added,   9 absent  superseded (see below)

## The 23 absent lines, adjudicated one group at a time.
NONE of them is missing work.  Each is a line main DELIBERATELY REPLACED with a
later form, and re-applying any of them would be a revert or a regression.

### b742c9b5 / tools/ci/repo_hygiene_gates.sh  (6 lines)
The gate declaration `run "every program is reachable" ... "\$ROOT/.../program_reachability_check.py" --strict`
and its 5-line comment.  Main carries the SAME gate at repo_hygiene_gates.sh:951 in the
form `"\$RUNTIME_ROOT/vibe-ic-marketplace/tools/program_reachability_check.py" --root "\$ROOT" --strict`,
and main's comment at :936 says in as many words: "This was first declared as
python3 \$ROOT/.../program_reachability_check.py".  That replacement IS patch
1b599dee ("the repair was trapped inside the verification it was repairing"),
which measures FULLY LANDED above.  Re-applying b742c9b5's line reverts 1b599dee.
ACTION: keep main's.

### b742c9b5 / tools/ci/gate_fixtures/every_program_is_reachable.py  (8 lines)
The fixture's copy-the-auditor-into-the-subject-tree block.  Same supersession:
1b599dee rewrote it.  MEASURED: main's copy of this file is BYTE-IDENTICAL to
origin/fix-whole-population-reachability's tip copy.  ACTION: keep main's.

### 02dc2f03 / INDEX.md (4) + PROGRAM_INVENTORY.json (4)
Pinned census counters as of 2026-08-26: "Total programs 1214", "any | 1205",
"count": 4207, "count": 2850, and two sha256_of_sorted_paths pins.  Main is 30+
versions later and has regenerated all of them.  The patch's actual INTENT here was
to REGISTER the new program, and that landed: main's INDEX.md carries
`extraction_credited_by_prose_only_check` at :360 and :1623.  Pasting the old
counters back would publish a false census.  ACTION: keep main's regenerated values.

### 02dc2f03 / extraction_credited_by_prose_only_check.py  (1 line)
`out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")`.
Main replaced this with the ATOMIC writer (`_atomic_artefact.write_text`, vibe-ic#1082)
so a reader never resolves a half-written report.  Re-applying is a straight
regression and a known ratchet offender.  ACTION: keep main's.

## Cross-check, independent of the line-set instrument
  - main vs origin/fix-whole-population-reachability TIP, its 4 touched files:
        program_reachability_check.py                          IDENTICAL
        test_program_reachability_check_sees_the_whole_tree.py IDENTICAL
        tools/ci/gate_fixtures/every_program_is_reachable.py   IDENTICAL
        tools/ci/repo_hygiene_gates.sh   differs ONLY by gates main added later
                                         (OpenSTA error-abort, unanchored process
                                         kill) plus one cosmetic backtick on an
                                         unrelated uncheckable_until string.
  - main vs origin/fix/flow-solidity-pwm4 TIP:
        phase1_post_process.py                                 IDENTICAL
        spec_conformance_check.py                              IDENTICAL
        test_extraction_credited_by_prose_only.py              IDENTICAL
        test_prose_port_extraction_survives_its_own_cleanup.py IDENTICAL
  - the two wirings the patches exist to create are BOTH live on main:
        repo_hygiene_gates.sh:951  run "every program is reachable" ... --strict
        flow yaml:646              advisory_program_exit_zero:
                                   extraction_credited_by_prose_only_check
  - the two prose fixes are live on main:
        _RE_L1_BULLET_PORT_HEADING at phase1_doc_one_shot_runner.py:2556 carries
        the sibling's `(?:[-*+]\s+|#{1,6}\s+)?` prefix  (f9f6d12a)
        _edit_looks_like_a_typo defined at :13679, called at :13670  (8206f4d0)

## VERDICT
There is nothing to re-derive.  The union of the seven has landed in full, by other
routes, and in two places main's form is strictly better than the branches'.
The branches are therefore safe to retire ONCE the owner has read this — but per the
brief they are NOT deleted here.

What remains worth doing, and is done next, is the FALSIFICATION the brief asks for:
prove the auditor that landed can actually say NO.

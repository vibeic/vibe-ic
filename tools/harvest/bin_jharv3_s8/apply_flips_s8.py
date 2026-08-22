#!/usr/bin/env python3
"""Append session-8 corrections to verdicts_shard_c.tsv and flip two verdicts.

Rows are only ever APPENDED to: the original evidence and every prior dated
correction stay readable, because a verdict whose reasoning was silently
rewritten cannot be checked by somebody who was not there.

Refuses rather than half-writing: the file must keep 110 rows and 3 fields per
row, and every path named here must be found exactly once.
"""
import sys, io

SRC = "verdicts_shard_c.tsv"
FLIPS = {}

FLIPS["/home/reyerchu/AI_IC_design/wt_jwire2"] = ("LANDED", """  ***VERDICT CHANGED RECOVER -> LANDED 2026-08-22T19:0xZ (jharv3, eighth session), judged against CURRENT origin/main ae78abb285630636b2f305f2ed4aef13f92201ed (v1.11.70), which is 673 commits past the a4caccefe every earlier line above was measured against. WHY IT MOVED: main took this branch in that window, at f26a5ccd99114b3f9ddca26473bf957f605ae0d8 "Merge remote-tracking branch 'origin/fix/jwire2-hygiene-wiring' into land/one-assembled". EVERY FILE MATCHES MAIN'S CONTENT: the directory on .121 was re-read today, read-only over the .102 hop -- HEAD has moved again, a00f53f20948 -> 4b1285a1865e -> c190bf024bc21567aeeea2d3ed7fbc0d3cc5c716, but its TREE is unchanged at f8b97313740e04d9adac9776194cd5f3cd609cc5, so the snapshot this row is about is the one session 5 measured. That tree holds 6504 files, and all 6504 (path,blob) pairs are pairs origin/main's HISTORY has held at that path; 0 are content main never held. Against the OLD main a4caccefe the same tree had 13 such pairs, and those 13 are exactly the work that landed: .github/PULL_REQUEST_TEMPLATE.md, .github/ppa_pr_answers.json, benchmark/CAPTURE_ROUTING.json, flow/phase1_phase2_phase3.yaml, programs/design_one_shot_runner.py, flow_gate_enforcement_audit.py, gatekeeper_review.py, pg_rail_geometry_check.py, ppa_pr_scope_check.py, slot_pad_budget_check.py and the three tests test_issue1347_ppa_pr_scope_is_wired_into_the_merge_gate.py, test_issue1347_slot_pad_budget_is_wired_into_the_flow.py, test_slot_pad_budget_check.py. Each was attributed to the main commit that took it (b6b068f05200, 2d98774e8ab2, f26a5ccd9911, bef9ee4e7454, 816e49ba079c, 59ebf85980b9, 115e43e093f4, ce90f11ec7ff, d3e1c5b8c838, 4b1285a1865e, 65edc900a490) -- note 4b1285a1865e, the head session 5 found on this disk, is now a commit ON MAIN. NOTHING OUTSIDE THE TREE: re-measured on the host, 6510 files on disk against 6504 tracked; the 6 extra are 5 .pytest_cache/ entries (a class main's own .gitignore declares at line 7) and the .git worktree-pointer file. git status --porcelain -uall reports 0 entries, 0 symlinks, 0 tracked paths missing from disk. Deleting this directory destroys nothing main does not already hold. Method and its self-test: bin_jharv3_s8/rejudge_vs_current_main.sh; report: REJUDGE_shard_c_s8_current_main_jharv3.md.***""")

FLIPS["/home/reyerchu/_ld/wt"] = ("LANDED", """  ***VERDICT CHANGED RECOVER -> LANDED 2026-08-22T19:0xZ (jharv3, eighth session). THE NAMED MISSING INPUT IS NOW SUPPLIED. The fifth-session note above holds this row at RECOVER for one stated reason: gitignored entries attributed to `benchmark-data/ic/*/clean_run_*/` (.gitignore:153) that nobody had looked at, and it refused to authorise deleting unexamined bytes. Those bytes have now been read. WHAT IS ACTUALLY THERE, measured on .121 today read-only over the .102 hop: 22061 files on disk, 21786 tracked, so 405 files exist that no commit holds -- 391 of them __pycache__/ and .pytest_cache/ (main's own .gitignore, lines 2 and 7), 1 the .git worktree-pointer file, and 13 content files. All 13 were copied off the host and examined, and their sha256 read back byte-identical to the sha256 measured on the host. NONE of them holds a finding, a measurement, or authored prose that main does not already have: (1) lessons.md, both copies, is git blob b94a8a184747a98a523f961ec9741ff53ac0bae0, which origin/main's history holds at EIGHT committed paths under benchmark-data/ic/*/... -- byte-identical, not merely similar; (2) ic_expert_db.md, both copies identical, is an extract of five design-class lessons whose text is verbatim in the COMMITTED vibe-ic-marketplace/plugins/vibe-ic/agents/ic_expert_db/ic_expert_db.json on main (checked by git grep -F on three distinct sentences, each hitting that file and only that file); (3) ic_expert_agent_handoff.json, both copies identical, is the prompt pack the committed program vibe-ic-marketplace/plugins/vibe-ic/programs/phase1_expert_parse_track.py assembles from that same DB; (4) expert_parse_track.json and (5) phase1_planned_consumer_starved_check.json differ between the two run directories in NOTHING but the embedded absolute run-directory path -- diff reports 4 hunks and 1 hunk respectively, every one of them a /home/reyerchu/_ld/wt/.../clean_run_vNNNN string -- and both carry verdict VACUOUS_PASS with 0 examined expectations; (6) cross_layer_reference_check.json is byte-identical across both runs, verdict VACUOUS_PASS, elements_examined 0, findings []; (7) docs/reports/wave76_skill_md_audit.json (.gitignore:103) is an audit result with skills_with_hits [], all four totals 0, files_modified [] and allowlisted []. A COUNT IN THE EARLIER NOTE WAS WRONG AND IS CORRECTED HERE: the 646 files under the clean_run_* directories are not 646 unexamined files -- 712 files under those paths are TRACKED (git's ignore rules do not apply to files already in the index), and only 12 of them are outside the index. THE COMMITTED SIDE, re-judged against CURRENT origin/main ae78abb285630636b2f305f2ed4aef13f92201ed rather than the stale a4caccefe: HEAD is unmoved at 31fb2c1efe49b8f2579fce73d1f18d1a60ca0cd5, its tree holds 21782 files, and every one of their (path,blob) pairs is a pair main's HISTORY has held at that path -- 0 that main never held, under BOTH mains. CLEAN ON DISK: git status --porcelain -uall reports 0 entries; the 130 index entries that are not regular files resolve to 126 symlinks and 4 gitlinks, 0 truly missing. Deleting this directory destroys nothing main does not already hold. Method and its self-test: bin_jharv3_s8/rejudge_vs_current_main.sh; report: REJUDGE_shard_c_s8_current_main_jharv3.md.***""")

rows = []
with open(SRC, encoding="utf-8") as f:
    header = f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) != 3:
            sys.exit(f"REFUSING: row has {len(p)} fields, not 3: {p[:1]}")
        rows.append(p)
if len(rows) != 110:
    sys.exit(f"REFUSING: expected 110 rows, found {len(rows)}")

seen = {}
for r in rows:
    seen[r[0]] = seen.get(r[0], 0) + 1
for path in FLIPS:
    if seen.get(path) != 1:
        sys.exit(f"REFUSING: {path} appears {seen.get(path,0)} times, not once")

changed = 0
for r in rows:
    if r[0] in FLIPS:
        new_verdict, note = FLIPS[r[0]]
        if r[1] == new_verdict:
            sys.exit(f"REFUSING: {r[0]} is already {new_verdict}; nothing to flip")
        if "\t" in note or "\n" in note:
            sys.exit("REFUSING: note contains a tab or newline and would break the TSV")
        r[1] = new_verdict
        r[2] = r[2] + note
        changed += 1
if changed != len(FLIPS):
    sys.exit(f"REFUSING: flipped {changed}, expected {len(FLIPS)}")

with open(SRC, "w", encoding="utf-8") as f:
    f.write(header)
    for r in rows:
        f.write("\t".join(r) + "\n")

from collections import Counter
c = Counter(r[1] for r in rows)
print(f"rows={len(rows)} flipped={changed} verdicts={dict(c)}")

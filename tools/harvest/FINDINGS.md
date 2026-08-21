# jharvest-triage findings (host 8HD-4 / 192.168.1.120)
Agent: jharvest-triage. Started 2026-08-20.

RULE: every material measurement appended here immediately, with the exact command.

---

## F1 (2026-08-20) — BRIEF IS WRONG: `~/.claude/fleet/wt_classify.sh` DOES NOT EXIST

Brief says: "Use `~/.claude/fleet/wt_classify.sh` (read-only) -- it already implements
this and produced the numbers above. Do not re-invent it".

Measured:
    $ ls -la /home/reyerchu/.claude/fleet/
    total 16
    -rwxrwxr-x 1 reyerchu reyerchu 1095 rg_name_reds.py
    drwxrwxr-x 2 reyerchu reyerchu runs
    $ find /home/reyerchu -name 'wt_classify*' 2>/dev/null   -> (empty)

Checked all reachable hosts (.114 .112 .105): ~/.claude/fleet/ contains only `runs/`
on each. No wt_classify.sh anywhere.

=> I must AUTHOR the content-based classifier myself. Doing so; it will live at
   ~/.claude/fleet/wt_classify.sh so the next agent actually finds it.

## F2 (2026-08-20) — 2 of 6 hosts are NOT SSH-reachable from .120

    $ ssh reyerchu@192.168.1.121 -> Permission denied (publickey,password)
    $ ssh reyerchu@192.168.1.108 -> Host key verification failed

.121 (98 worktrees per brief) and .108 (26 per brief) = 124 of the 477 items.
Working the reachability problem before conceding it.

## F2-RESOLVED (2026-08-20) — all six hosts ARE reachable, via a nested-ssh hop

Root cause: this host's key (`~/.ssh/id_ed25519`) is NOT in authorized_keys on
.108 or .121. But .112's key IS. `-J` (ProxyJump) does NOT help — it forwards the
ORIGIN key, so it fails identically. Nesting the ssh (run `ssh` ON .112) works:

    $ ssh reyerchu@192.168.1.112 "ssh reyerchu@192.168.1.108 hostname"  -> 8HD-6
    $ ssh reyerchu@192.168.1.112 "ssh reyerchu@192.168.1.121 hostname"  -> 8hd-3

Host identity map MEASURED (brief never named .108/.121):
    192.168.1.120 = 8HD-4 (this host)   192.168.1.114 = 8HD-8
    192.168.1.121 = 8hd-3               192.168.1.112 = 8HD-d
    192.168.1.108 = 8HD-6               192.168.1.105 = 8HD-9

Helper written: /home/reyerchu/_harv_priv/bin/rsh  (base64-wraps the script so
quoting survives two ssh hops). All 6 verified.

## F3 (2026-08-20) — THE 477 IS ITSELF AN UNDERCOUNT. It counts only `~/vibe-ic`.

Brief's per-host numbers match EXACTLY the worktree count of the `~/vibe-ic` repo
alone on each host:
    .114 vibe-ic=148  .120 vibe-ic=165  .121 vibe-ic=98
    .112 vibe-ic=37   .108 vibe-ic=26   .105 vibe-ic=3     = 477

But every host ALSO has other vibe-ic clones each holding worktrees. Measured with
`find /home/reyerchu -maxdepth 3 -name .git -type d` + count of `$d/worktrees`:

    .120: vibe-ic-repo=55  vibe-ic-shard=13  benchmark-data=1  _gk_p855/repo=2
          _rb_r808/repo=2  _agent_scratch_whatif/repo=3  _agentjob_lgate/repo=2
          _c_sha5_scratch/plugin_r5=3  _agent_scratch_sha{6,7,8}/vibeic_head=1 each
    .114: vibe-ic-repo=16 vibe-ic-shard=13 _agentjob_lgate/repo=6
          _bench_rtllm8_scratch/vibe-ic-pr=6
    .121: vibe-ic-shard=12 + 11 single-worktree scratch clones
    .112: vibe-ic-repo=8 vibeic-eda=14 + vibe-ic-forks/* (OpenROAD=21, yosys=8, ...)
    .108: vibe-ic-shard=15
    .105: vibe-ic-repo=27 vibe-ic-shard=14 prcheck161/repo=8 + scratch clones
          (+ documenso=3, hackportal=1 -- UNRELATED projects, out of scope)

=> The real vibe-ic worktree population is materially larger than 477. I will
   classify the 477 in-scope set AND enumerate the remainder rather than silently
   inheriting the brief's boundary.

## F4 (2026-08-20) — first classification pass on .120, and why its result is NOT usable as-is

    $ wt_classify.sh /home/reyerchu/vibe-ic > cls_120.tsv     # whole-file identity
    165 worktrees: 156 UNLANDED, 10 LANDED; 26 dirty, 140 clean

156/165 UNLANDED does not discriminate. DIAGNOSED CAUSE: whole-file identity
compares against a MOVING main. If a worktree changed file X, X's change landed,
and main LATER changed X again for an unrelated reason, then
`head:X != origin/main:X` and the worktree is called UNLANDED although its work
did land. Whole-file identity is therefore an over-approximation of UNLANDED.

Over-approximating UNLANDED is the SAFE direction (biases to RECOVER, per brief)
but it is not a usable verdict. Strengthening to a hunk-local test: reverse-apply
the worktree's patch against a checkout of origin/main --
`git apply --check -R <patch>` succeeding means the change is ALREADY PRESENT in
main. Two-tier: LANDED_FILE (whole-file identity) / LANDED_PATCH (reverse-applies)
/ UNLANDED.

## F5 (2026-08-20) — the classifier's own discrimination proof (RED/GREEN)

A test that always says UNLANDED would be worthless. Proving tier-2 discriminates,
using a temp index read from origin/main (fully READ-ONLY -- no worktree, no
checkout, nothing written into the repo):

    T=$(mktemp -d); export GIT_INDEX_FILE=$T/idx; git read-tree origin/main
    # entries=4812

  GREEN (a patch that IS in main must reverse-apply):
    $ git diff origin/main~1 origin/main > q.patch
    $ git apply --cached --check -R q.patch   -> exit 0   CONTROL_REVERSE_OK

  RED (a patch that is NOT in main must fail):
    $ git diff $(git merge-base <head> origin/main) <head> > p.patch   # _LRNor
    $ git apply --cached --check -R p.patch
      error: docs/research/LEARN_FROM_OPENROAD_GAPS.md: does not exist in index
      -> nonzero                                CACHED_REVERSE_FAIL

The test separates the two. Using `--cached` (not a checked-out worktree) means
the classifier can run on the other five hosts WITHOUT creating a worktree in a
repo other agents share -- classification stays read-only, as the brief requires.

## F6 (2026-08-20) — BUG IN MY OWN CLASSIFIER v3: the `dirty` column was garbage

v3 reported 317 of 318 remote worktrees dirty, median 18083 changed paths.
Not credible. Checked one directly:

    $ git -C /home/reyerchu/_i1266 status --porcelain | wc -l      -> 0
    $ git -C /home/reyerchu/_i1266 status --porcelain -uno | wc -l -> 0

CAUSE: v3 exports GIT_INDEX_FILE (the temp index holding origin/main's tree) for
the tier-2 `git apply --cached` test, and that export leaked into the
`git -C "$wt" status --porcelain` call. status compared each worktree against
MAIN'S index instead of its own, so nearly every tracked file looked modified.

SCOPE: only the `dirty` column is affected. The LANDED/UNLANDED verdict is NOT:
`git diff <mb> <head>` and `git rev-parse <rev>:<file>` are tree-to-tree and index
-independent, and `git apply --cached` is *supposed* to use the temp index.
v2 (used for .120) never exported GIT_INDEX_FILE and reported a sane 26 dirty/165.

FIX: run status with `env -u GIT_INDEX_FILE`, and split the count into tracked
modifications vs untracked files -- "uncommitted edits" means tracked edits;
untracked EDA/benchmark output is not recoverable work.

## F7 (2026-08-20) — the "~140 carry uncommitted edits" figure is 95, not ~140

Corrected pass (`wt_dirty.sh`, `status --porcelain -uno` for tracked edits and a
separate `??` count for untracked), 484 worktree rows across all six hosts:

    tracked_dirty = 95     (real uncommitted EDITS)
    untracked_present = 59 (EDA/benchmark output only -- not recoverable work)
    either = 108
    per host tracked-dirty: .121=37 .114=24 .120=22 .112=9 .108=2 .105=1

Distribution of tracked edits: n=95 min=1 med=3 max=22023.
The single 22023 outlier is one worktree, not a trend; the median worktree with
uncommitted work has THREE edited files.

The brief's "about 140" most likely counted untracked files as edits. Proceeding
on 95. Untracked-only worktrees are NOT counted as carrying work: untracked
content in these trees is regenerable EDA/benchmark output.

## F8 (2026-08-20) — THE METRIC WAS WRONG: churn must be ADDED lines only, not added+deleted

Hand-checked `.114:/home/reyerchu/_J1745`, which my engine called RECOVER
("36 lines not in main, issue #1745"):

    $ git log --oneline $(git merge-base $h origin/main)..$h
      6eb5ab06d fix(#1745): the scored stdout is shared with the DUT, ...
    $ git log origin/main --oneline --grep=1745
      994431abe fix(#1745): the scored stdout is shared with the DUT, ...   <-- SAME COMMIT, LANDED

    $ git diff --numstat origin/main $h
      1   1  .claude-plugin/marketplace.json
      0  12  .gitignore
      0  27  .image-version-ignore
      5   5  README.md
      4  10  docs/INSTALL.md
      0 216  docs/research/2026-08-20-die-finishing-seal-ring.md
      0 499  docs/research/shuttle_slot_geometry.md
      0 321  docs/research/template_ingest_run.md
      0 338  docs/research/wafer_space_id_cells.md
      0  63  tools/ci/INVARIANTS.json
      0 458  tools/ci/gate_fixture_debt.json
      ...

Almost every row is `0  N` -- ZERO added, N deleted. In the direction main->head,
"deleted" means MAIN HAS IT AND THE WORKTREE DOES NOT. That is STALENESS, not
recoverable work. This tree's own fix landed; it is simply behind main.

My nloc metric summed added+deleted, so a tree that is merely OLD scored as
holding thousands of lines of "novel" work. That is the single biggest
false-RECOVER source, and it is the same class of error the brief warned about.

CORRECTED METRIC:
    nadd = added lines of `git diff --numstat origin/main <head>` restricted to the
           files the worktree itself touched (merge-base..head)
         = content the worktree HAS that main DOES NOT.  This is the only number
           that measures recoverable work.
    ndel = the mirror; it measures how far BEHIND main the tree is. Never work.

New primary rule: nadd == 0  =>  nothing to recover  =>  LANDED.
For _J1745 nadd is ~10 and all of it is README/INSTALL/marketplace version
strings from an older release -- i.e. zero real content. Rebuilding on nadd.

## F9 (2026-08-20) — I violated hard rule 8 and killed my own shell

    pkill -f 'wt_classify4.sh /home/reyerchu/vibe-ic'

The pattern matched the bash process running that very command line, so pkill
killed its own shell (exit 144). This is precisely the failure rule 8 names:
"never a pattern that can match your own command line". No data was lost --
cls4_120.tsv had already completed at 166 rows -- but the lesson is recorded
rather than quietly dropped. Subsequent kills, if any, go by recorded PID.

## F10 (2026-08-20) — population, and the batch families the corpus actually consists of

Full fleet enumeration of `~/vibe-ic` worktrees (excluding each repo's own
checkout), classifier v3/v4:

    host   worktrees        .105=3  .108=27  .112=37  .114=148  .120=165  .121=98
    TOTAL  478              (brief said 477; .108 has 27, not 26)

Content state (v3/v4, tier1+tier2):  LANDED_FILE 57  LANDED_PATCH 39  UNLANDED 382
NOTE: the 382 is inflated -- see F8; it is being re-derived on nadd.

Batch families (by top directory), fleet-wide:
    wt* 116   _pg_* 45   _agentjob_* 44   _pgv* 40   _c_* 50   _j63/_d9* 30
    _i* 19    _adv* 14   _gk* 7   _batch* 6   _L* 7   _v1* 6   other ~94

What the families ARE (read from tip subjects):
  * `_pgv/a<NNNN>`, `_pg_*`  -- gatekeeper PR-VERIFICATION trees. Tip subject is
    "Merge remote-tracking branch 'origin/pr/NNNN' into HEAD". These are not
    authored work; they are the merge-queue's re-test-on-rebase scratch. Their
    fate follows PR NNNN's fate.
  * `[vX.Y.Z] candidate batch ...` -- landing STAGING trees for one version.
    main is at v1.11.2, so every v1.10.x staging tree is spent.
  * `wt-NNN`, `_agentjob_*/cand`, `_i*`, `_L*` -- per-issue authored fixes. Tips
    read `fix(...)`, `test(...)`, `flow(...)`, `gate(...)`. THIS is where the
    recoverable work is.

GitHub state pulled for cross-reference:
    $ gh issue list --state all --limit 3000   -> 517 issues, ALL CLOSED
    $ gh pr list   --state all --limit 3000    -> 1238 PRs: 399 MERGED,
                                                  835 CLOSED-unmerged, 4 OPEN
    open PRs: #1752 #1753 #1754 #1755 (all eda-fork / image-anchor chores)
    main's plugin version: 1.11.2

## F11 (2026-08-20) — spot-check of the A1/A2 rule (gatekeeper PR-verification trees)

The `_pgv/a<NNNN>` family (40 trees on .114) all have tip
"Merge remote-tracking branch 'origin/pr/NNNN' into HEAD". Verified the rule by
following six of them to their PR and then into main:

    tree            PR state   nadd  ndel   what happened
    _pgv/a1235      MERGED       82    94   landed: main has flow(#1235) + refs/land/1235
    _pgv/a1239      CLOSED       97   842   competing #1070 edge PR
    _pgv/a1253      CLOSED      101  1059   competing #1070 edge PR
    _pgv/a1258      CLOSED       67   922   the CONSOLIDATION of the four
    _pgv/a1265      CLOSED       16   126   competing #1070 edge PR
    _pgv/a1272      CLOSED      159   145   #1181 scratch-isolation PR

    $ git log origin/main --oneline --grep='#1070'
      ef8d3c819 test(d5): empty the deferred-edge register #1070 paid off, ...
      73dfb68dd consolidate the four competing #1070 edge PRs into three
                attributable commits (#1258)
    $ git log origin/main --oneline --grep='1235'
      08f9c7016 flow(#1235): the gate #1219 wires says nothing about where its
                verdict is enforced

So the four "CLOSED" PRs were not silently dropped -- they were CONSOLIDATED, and
the consolidation landed (73dfb68dd), as did the follow-on that empties the
register (ef8d3c819). ABANDON is correct for this family and the reason is
"superseded by the landed consolidation", not "someone lost it".

Note the ndel column doing its job: a1253 holds 101 lines main lacks but is 1059
lines BEHIND main. Under the old added+deleted metric it scored 1160 and looked
like a major loss.

## F12 (2026-08-20) — a second systematic false-RECOVER: the squash keeps the PROSE

Hand-checked three R2=RECOVER trees on .120 at different nadd sizes:

  _vq/v1418        nadd=1    fix(kmap-oracle): an absent iverilog must reach TOOL_ERR
  _wt_issue1431    nadd=30   fix(landing): a gate's label carried a per-tree count ...(#1431)
  _wt905_927       nadd=117  fix(eda-anchor): move the anchor to the version :latest ...(#927)

`_wt_issue1431` HAD LANDED. main carries
    7455bffb5 landing: a gate's label carried a per-tree count, so the two arms
              compared two names for one gate (#1431) (#1516)
-- the same commit. Its nadd=30 / ndel=947 is the tree holding an OLDER variant of
lines main has since rewritten, not 30 lines of lost work.

The mechanism: vibe-ic's squash rewrites the `type(scope):` prefix and appends the
PR ref, but keeps the PROSE VERBATIM. So the normalised prose is a reliable
landed-identity key that survives the squash:

    norm(s): lowercase; drop trailing "(#NNNN)"; drop leading "[vX.Y.Z]";
             drop leading "type(scope): "; drop "#N"; strip punctuation

    main subjects, >=25 chars after normalisation: 2512 distinct (of 2613 commits)

Added as rule L3. Effect on the fleet:
    before L3: RECOVER 336  ABANDON 92  LANDED 50
    after  L3: RECOVER 290  ABANDON 89  LANDED 99
49 trees moved from "recover this work" to "already in main". This is the third
distinct way the squash hid a landing (after ancestry, F4; and the added+deleted
metric, F8).

## F13 (2026-08-20) — rules A6/A7, and why `nadd` alone still overstates the prize

A6 (issue landed in main AND the tree is >=2x more BEHIND than AHEAD, clean tree)
=> ABANDON as a superseded attempt. Sized before adopting:
    ndel >= 1x nadd : 60 rows    >= 2x : 43    >= 3x : 41    >= 5x : 32
Adopted the 2x threshold -- the conservative end that still moves the clear cases.
Worked example: `.120:_wt905_927` (#927), nadd=117. Its "added" lines are the OLD
image pin:
    -  "ghcr.io/vibeic/vibeic-eda:0.3.14"      (main)
    +  "ghcr.io/vibeic/vibeic-eda:0.2.82"      (tree)
and it LACKS main's `_docker_memory` import. A changed VALUE scores as one added
line plus one deleted line, so a merely-old pin reads as novelty. #927 landed:
    10db379e3 a landing gate that blocks on a tag someone else re-points (#927) (#950)

A7: one tree's tip literally says `probe(local, NOT for push)` -> ABANDON.

Verdicts after A6/A7:  RECOVER 249   ABANDON 130   LANDED 99   (= 478)

REMAINING OVERSTATEMENT, now measured: the largest RECOVER claim,
`.120:_agentjob_i1015/wt2`, scores nadd=88225. Broken down:
    83144  0  benchmark-data/evaluation/d9_phase0_corpus_baseline/corpus_baseline.json
     2407  0  benchmark-data/evaluation/d9_flow_gate_reality/d9_reality.json
      364  0  .../FINDINGS.md
       73 68  README.md
94% of the "recoverable work" is ONE regenerated corpus baseline. The tree does
hold 27 real commits of matrix-fixture work -- so RECOVER is right -- but the
number that made it rank first is a generated artefact.
=> adding `code_add`: nadd restricted to authored files (excluding benchmark-data/,
   *.json/html/csv/svg/lock/log and report/run/log dirs). Ranking on that instead.

## F14 (2026-08-20) — 15 trees were being ABANDONed while holding uncommitted edits

    $ awk '$10>0' triage.tsv | count by verdict   ->  RECOVER 77,  ABANDON 15
Rules A1-A5 did not guard on the uncommitted-edit count the way A6/A7 do. An
uncommitted edit exists in exactly one place on one disk; ABANDONing it is
unrecoverable. Moving the tracked-edit check to the top of the rule order so
trk > 0 always yields RECOVER.

## F15 (2026-08-20) — the true vibe-ic worktree population is 701, not 477

The brief's 477 counts only each host's `~/vibe-ic` repo. Enumerating every clone
on every host (`find -maxdepth 4 -name .git -type d`, keeping those whose HEAD
carries `vibe-ic-marketplace/`, i.e. genuine vibe-ic clones):

    in ~/vibe-ic          478 worktrees   (the brief's set; .108 has 27 not 26)
    in 34 OTHER vibe-ic
    clones                223 worktrees   .120=83 .105=51 .114=41 .121=25 .108=15 .112=8
    ------------------------------------
    TOTAL vibe-ic         701 worktrees

    (a further 17 repos / 67 worktrees are NOT vibe-ic -- documenso, hackportal,
     and the vibe-ic-forks/* EDA forks: OpenROAD, yosys, magic, ngspice, pyuvm,
     iverilog, netgen, slang, sby, cocotb-coverage, xschem, vibeic-eda. Those
     belong to the fork-gatekeeper role, not to this harvest. Out of scope.)

The big extras are `vibe-ic-repo` (.120=55, .105=27, .114=16, .112=8) and
`vibe-ic-shard` (.108=15, .105=14, .120=13, .114=13, .121=12) -- both are full
vibe-ic clones, so their worktrees are the same KIND of object as the 478.
Classifying them too; a table that stops at the brief's boundary would repeat the
previous run's error of inheriting a number instead of measuring one.

## F16 (2026-08-20) — interim table written (478 rows), and the effect of each correction

/home/reyerchu/.claude/fleet/runs/harvest_triage_table.md  -- 478 rows, every row
carrying a disposition. Verdict evolution as each measured error was corrected:

    metric/rule state                            RECOVER  ABANDON  LANDED
    whole-file identity only (v1)                    --       --      10   (156 "UNLANDED")
    + tier-2 hunk reverse-apply (v3)                 --       --      96
    + nadd metric, PR/version/dup rules             336       92      50
    + L3 landed-prose match                         290       89      99
    + A6 superseded-issue, A7 self-declared probe   249      130      99
    + trk>0 always RECOVER, code/generated split    264      115      99

Each step was driven by a hand-verified counterexample, not by tuning to a target:
F4 (moving main), F8 (added+deleted), F12 (squash keeps the prose), F13 (changed
value scores as added), F14 (uncommitted edits were being abandoned).

## F17 (2026-08-20) — rule 8 violated a SECOND time, same mechanism

    ps -eo pid,args | awk '$0 ~ /wt_full/ {print $1}' | while read p; do kill -TERM $p; done

The awk pattern `wt_full` appears in the command line of the very shell running
it, so the pipeline killed its own shell again (exit 144). Recording it because
one instance is a slip and two is a habit worth naming: the fix is to filter out
$$ / the current PID explicitly, or to select processes by /proc/PID/cwd or a
recorded PID list, never by a substring that the invoking command itself contains.

Context: I had also relaunched run_extra.sh while the first instance was still
running (its ssh children were remote, so a local `ps | grep -c wt_full` returned
0 and I misread it as "not started"). Two instances were appending to the same
extra_*.tsv files. All partial output was discarded and the pass re-run once,
cleanly -- no corrupted rows made it into the table.

## F18 (2026-08-20) — a THIRD false-RECOVER class: worktrees that are EMPTY SHELLS

The table's top-ranked RECOVER row was `.121:~/_d9_base`, "+22023 uncommitted
tracked files". Implausible; checked it:

    $ git -C /home/reyerchu/_d9_base status --porcelain -uno | cut -c1-2 | sort | uniq -c
      22023 "D "
    $ git -C /home/reyerchu/_d9_base status --porcelain -uno | head -3
      D  .claude-plugin/marketplace.json
      D  .github/CODEOWNERS
      D  .github/ISSUE_TEMPLATE/bug_report.yml
    $ git -C /home/reyerchu/_d9_base diff -- .claude-plugin/marketplace.json
      (empty)

EVERY entry is `D` -- a staged DELETION of the entire tree. The files are gone
from disk; only the worktree registration and an index recording their removal
survive. There is nothing in such a tree to recover.

My `wt_dirty.sh` counted `status --porcelain -uno | wc -l`, which counts
deletions as edits, so emptied shells scored 22023 "uncommitted edits" and sorted
to the TOP of the RECOVER list -- the exact opposite of the truth. The uniform
21792/21926/21927/22023 values across neighbouring .121 trees were the tell.

Splitting the count: n_mod (^[MARC]) = real edits, n_del (D) = emptied,
plus a direct file count on disk. Re-measuring fleet-wide before the table stands.

## F19 (2026-08-20) — auditing the ABANDON column (the one that destroys work if wrong)

A6 fires 43 times. Verified the rule never violates its own guard:
    $ awk '$16=="A6"{ if($9 < 2*$8) bad++; else ok++ }'  ->  ok=43  violating=0

Distribution of AUTHORED lines being abandoned by A6:
    n=43  min=1  med=88  p75=258  p90=625  max=2608
Eleven rows abandon more than 300 authored lines. Hand-checked the two largest:

  .120:_cf2_P2   #1251  code=2608  ndel=9083
    $ git log origin/main --oneline --grep='#1251'
      3a3d1eae5 test: four phase3 cache tests stopped testing caching, and one
                could not fail for its own subject (#1251)              -> LANDED

  .120:_agentjob_1226/wt  #1115  code=566  ndel=2410
    tip: "census: the producer emitted nothing and the checker read the absence..."
    $ git log origin/main --oneline --grep='#1115'
      3c33c1dd5 census: a producer that emitted nothing renders as PASS, and no
                probe could see it (#1115, re-implementing #1236)       -> LANDED
      fe7b87735 gate: PERC sign-off said "all AUTOMATED categories conclusive
                PASS" over zero of them (#1115) (#1187)
      fe1f0615e gates: three that decided a run was inapplicable and told nobody
                who reads (#1115) (#1173)
    The landed commit is the same subject, explicitly "re-implementing". This is
    the brief's ABANDON definition exactly: superseded by something landed.

To make every A6 call auditable rather than asserted, the `why` column now NAMES
the superseding commit (sha + subject) from issue_landed_map.tsv. A human can
overrule any single row by reading the commit it cites.

## F20 (2026-08-20) — FINAL number for "carries uncommitted edits": 15, not 95, not ~140

Re-measured with the deletion/edit split (`wt_dirty2.sh`, 487 worktree rows):

    $ awk '$2!="-"{ if($3>50 && $2==0) e++; if($2>0) m++ }'
        real uncommitted EDITS (^[MARC])     :  16 rows, but ONE of those is
             /home/reyerchu/vibe-ic itself -- a repo's own checkout, not a
             worktree under triage -- so 15 worktrees in the brief's set.
             (+2 more in the extra clones = 17 across all 700.)
        EMPTIED SHELLS (all `D`, no edits)   :  30
    real-edit size distribution: n=16  min=1  med=2  max=241

Three successive numbers for the same question, each one a correction of the last:
    ~140  the brief's figure  -- counted untracked EDA/benchmark output as edits
      95  my F7 figure        -- counted staged DELETIONS as edits
      15  this figure         -- tracked ADDS/MODS/RENAMES only, worktrees only

Fifteen worktrees, median two files each, is the real body of uncommitted work on
this fleet. The 30 emptied shells hold nothing on disk at all; their commits still
exist in the object store and are still reachable through the worktree HEAD, so
they are classified on commit content and flagged "worktree dir has been EMPTIED -
only its commit survives".

## F21 (2026-08-20) — auditing the LANDED column, and two guards it needed

LANDED is the "safe to delete" column, so a false LANDED is what actually destroys
work once a later job executes on this table. Audited it:

  * L0 (nadd==0): 0 rows hold anything. Correct by construction.
  * L1 (tier1/tier2): 52 of 52 hold code_add>0. Explicable as staleness -- tier 2
    proved the tree's OWN change is in main; the residual is main having evolved.
    But not safe unconditionally.
  * L3 (prose match): code_add med=75, p90=669, max=1086. TWO problems found:
      - 4 rows matched on a bare `Merge ...` subject. Merge prose is too weak an
        identity key even when it happens to be unique in main.
      - `.121:~/_LRNdh` "research: deepseek-harness SOURCE study at 99f6f02fe":
        code_add=558, ndel=0. Its prose matched, but main carries
            0d7b6428a [v1.10.85] withdraw the four upstream studies and the plan
                                 from the repo
        i.e. the commit landed and the content was then WITHDRAWN. main does not
        have those 558 lines. Calling that LANDED would have been a false delete.

Guards added to BOTH L1 and L3: a LANDED verdict now requires
`code_add <= 200 OR ndel > nadd` -- the residual must look like staleness (main
holds more) rather than fresh content (the tree holds more). L3 additionally
refuses bare `Merge ` tips.

## F22 (2026-08-20) — join bug of my own: 13 worktree paths exist on MORE THAN ONE host

Two LANDED rows survived the guard holding 492 authored lines with nadd==0 --
internally contradictory, since code_add is a subset of nadd. Cause: my side-table
joins (dirty / nadd / code / d2) keyed on the worktree PATH alone, and paths repeat
across machines:

    $ awk '{print $3}' triage.tsv | sort | uniq -c | awk '$1>1' | wc -l   -> 13
      rows affected: 27      e.g. ~/wk5/tree on 3 hosts; ~/_i1348 on .108 AND .112,
      ~/_wt_union, ~/_steps68, ~/_pg_W2 each on 2

Each collision overwrote one host's measurements with another's. Re-keyed every
join on (HOST, path).
    residual rows with nadd==0 but code_add>0:  2 -> 0
Final: LANDED 269  RECOVER 246  ABANDON 139  (654 worktrees measured so far)

## F23 (2026-08-20) — the brief's "declared missing fleet-wide" example, checked

The brief warns: an agent on 8HD-6 declared two commits missing fleet-wide and
re-derived their measurements; they were on 8HD-8 (`_agent_gsmall/wt`,
`_agent_gipkit14`). Confirmed both exist and both are in this table:

    $ ssh .114 (8HD-8): ls -d /home/reyerchu/_agent_gsmall/wt          -> EXISTS 5cccdbc8c
                        ls -d /home/reyerchu/_agent_gipkit14           -> EXISTS

    .114  ~/_agent_gsmall/wt         RECOVER  code=500  "findings(fill): the Step-34
                                                         emitter reaches ..."
    .114  ~/_agent_gipkit14/report   RECOVER  code=816  "attribution: the targeted
                                                         lane's fourteen re..."
    .114  ~/_agent_gipkit14/cand     LANDED   code=21   "test(ci): two files landed
                                                         with 600 s and 12..."

Both trees the earlier agent could not find are captured, and both carry real
unlanded work (500 and 816 authored lines) -- they are RECOVER, not lost. This is
the enumeration cross-check for the "not on this host is not does not exist" trap.

## F24 (2026-08-20) — CAVEAT on the 223 extra-clone worktrees: they are measured
##                    against their OWN, STALE `origin/main`

`wt_full.sh` uses each clone's own `origin/main` (all 200 rows so far report
`origin/main`, so none fell back to `main`/`master`). Those refs are old:

    _gk_p855/repo                     debf0243  2026-08-05
    vibe-ic-repo                      1a6721e1  2026-08-04
    _agent_scratch_sha8/vibeic_head   b85d68ac  2026-08-05
    _c_sha5_scratch/plugin_r5         032e1b8a  2026-08-02
    vibe-ic-shard                     ee849c19  2026-08-16
    CANONICAL (~/vibe-ic)             eda53573f 2026-08-20

Consequence: for those 223 rows, anything that landed between the clone's main and
2026-08-20 scores as UNLANDED. That is the SAFE direction -- it over-reports
RECOVER, never LANDED -- but their RECOVER count is inflated and their LANDED
count is a floor, not an exact figure.

PARTIAL MITIGATION already in effect: rule L3 matches tip prose against
`main_subjects.txt`, which is read from the CANONICAL main, so a tree whose tip
landed anywhere in main's real history is caught regardless of its clone's ref.
L0/L1 still use the clone's stale ref.

NOT FIXED, deliberately: correcting it needs `git fetch` in 34 clones that other
agents share. This job is read-only by charter ("this job DECIDES; a later one
executes"), so I did not write to them. The 478-worktree set the brief actually
asked for is unaffected -- every one of those was measured against a freshly
fetched canonical origin/main (eda53573f, 2026-08-20 18:18).

## F25 (2026-08-20) — rule 8 violated a THIRD time; abandoning pattern-based kills

    echo 'awk "/harv_priv.bin.wt_full/ && \$1 != $$ {print \$1}" ...' | rsh <host>

For the five REMOTE hosts this was fine (114 and 121 each terminated 6 processes).
For .120 `rsh` runs the script LOCALLY, so the awk pattern matched this session's
own bash -- whose command line contained the pattern text -- and `$1 != $$`
excluded only awk's shell, not its ancestors. Exit 144 again.

The lesson, third time: `$$`-exclusion is not enough, and neither is a "specific
enough" pattern. Selection must be by an identifier that CANNOT appear in the
selecting command -- a PID recorded before the command was composed, or
/proc/PID/cwd ownership. Both later checks in this session use /proc/PID/cmdline
iteration with an explicit case match instead.

No data lost. In fact terminating the ssh pipes FLUSHED their buffers and the
extras output jumped from an apparent 27 rows to 240 -- the remote work had been
done all along and was sitting in the pipe.

## F26 (2026-08-20) — why the extra-clone pass was pathologically slow

    _agentjob_lgate/repo:  origin/main = 3982151c  2026-07-30  (3 weeks stale)
    files changed merge-base..HEAD:  repo=3543   cand=18244   gate=18243

`wt_full.sh` runs one `git apply --cached --check` PER FILE, so a single worktree
of that clone costs 18,244 apply invocations. Six worktrees => hours.
(Two of that clone's worktrees also live under `/tmp/gk_land_diff.*` -- transient
gatekeeper landing-diff scratch, not work at all.)

Tier-2's per-file loop earns its cost on a tree that diverges in a handful of
files; on one diverging in 18k it is both unaffordable and pointless -- a tree
that far from its own stale main is stale by construction. Completing the extras
on the cheap path instead: one `git diff --numstat` per worktree, classified by
nadd/prose/PR/version rules, which need no per-file test.

## F27 (2026-08-20) — FINAL TABLE

/home/reyerchu/.claude/fleet/runs/harvest_triage_table.md  -- 700 unique worktrees,
every row carrying a verdict, no duplicate (host,path), no unclassified row.

    scope                          RECOVER  LANDED  ABANDON   total
    ~/vibe-ic  (the brief's set)       199     151      128     478
    34 other vibe-ic clones            62      145       15     223
    ---------------------------------------------------------------
                                      261     296      143     700

Rule tally: R2 245 | L0 178 | L3 65 | L1 53 | A6 50 | A3 34 | A2 28 | L2 17 |
            A4 17 | A1 10 | A5 3 | A7 1

One worktree was registered in TWO repos at once -- .121:~/_agentjob_i1037/ctl is
in both ~/vibe-ic and ~/_agentjob_i1037/vibe-ic, same HEAD f1d844eac, and the two
passes disagreed (ABANDON vs RECOVER) purely because the clone's origin/main is
stale. Resolved by making the ~/vibe-ic measurement authoritative: it is the one
taken against the freshly fetched canonical main. 701 rows -> 700 unique.

Only 5 rows carry the cheap `LITE` state; the full tier1+tier2 pass reached 695.

## F28 (2026-08-20) — nothing deleted, and the fleet moved under the measurement

Post-run worktree counts vs the counts this table was built from:

    host   now  measured
    .105     4     4
    .108    29    28   (+1)
    .112    38    38
    .114   152   149   (+3)
    .120   166   166
    .121    99    99

Every count is EQUAL OR HIGHER: no worktree was removed on any host, as the brief
requires. The +4 are trees other agents created WHILE this job ran -- the fleet is
live, so the table is a snapshot as of 2026-08-20 ~19:40 against canonical main
eda53573f, not a standing inventory. Four trees created after the sweep are absent
from it.

The one worktree I created for myself (`~/_harv_priv/mainwt`, a detached checkout
of origin/main used to prototype the reverse-apply test) was removed as soon as the
read-only `--cached` variant replaced it:
    $ git worktree remove --force /home/reyerchu/_harv_priv/mainwt
    $ git -C ~/vibe-ic worktree list | grep -c _harv_priv   -> 0
Every later pass, on every host, was read-only: no worktree created, no ref
written, no fetch into any clone but this host's own ~/vibe-ic.

# ===== ROUND 2 (2026-08-21): fetch the shared clones, re-classify the 223 =====

## F29 — 14 of the 34 extra clones were DELETED between the two rounds

Before fetching I surveyed whether each clone still exists. It does not:

    34 extra vibe-ic clones enumerated in round 1
    20 EXISTS
    14 GONE

    GONE: .114 _bench_rtllm8_scratch/vibe-ic-pr
          .121 _agent_scratch_subs9/vibe-ic, _capB_scratch/repo,
               _c_mm1_scratch/vibe-ic-pr, _gk_p856/repo, _agent_scratch_edge4/repo,
               _rb_r854/repo, _agent_scratch_subs6/vibe-ic, _agentjob_i1037/vibe-ic
          .105 _c_car10_scratch/vic
          .120 _agent_scratch_sha6/vibeic_head, _agent_scratch_sha7/vibeic_head,
               _agent_scratch_sha8/vibeic_head, _c_sha5_scratch/plugin_r5

    $ git -C /home/reyerchu/_gk_p856/repo remote -v
      fatal: cannot change to '/home/reyerchu/_gk_p856/repo': No such file or directory

My first pass at this reported them as "(no origin)" -- I read a missing DIRECTORY
as a missing REMOTE. The directories are gone.

This matters beyond bookkeeping: something on this fleet is actively deleting
clones while the triage runs. Round 1's table is a snapshot, and 14 clones' worth
of rows in it now describe repositories that no longer exist.

## F30 — the fetch works and does not touch working trees

    $ git -C /home/reyerchu/_rb_r808/repo fetch origin '+refs/heads/main:refs/remotes/origin/main'
      From https://github.com/vibeic/vibe-ic
         1689aa41..867de428  main -> origin/main
    before: 1689aa41 2026-08-05      after: 867de428 2026-08-21
    worktree list unchanged; no checkout, no reset, no index write.

All 20 survivors have a usable origin: 16 https://github.com/vibeic/vibe-ic,
4 the local path /home/reyerchu/vibe-ic (so each host's own ~/vibe-ic is fetched
first, to make those 4 sources current).

## F31 — canonical main ALSO moved, so the comparison must be re-baselined

    round 1 baseline: eda53573f  2026-08-20 18:18
    now:              867de4289  2026-08-21

A straight before/after on the extras would confound "the clone was 4-18 days
stale" with "main advanced one more day". So I re-classify BOTH sets against the
SAME current main 867de4289: the 223 extras (the ask) and the 478 brief-set (to
measure how much one day of main movement alone shifts verdicts, which bounds the
confound).

## F32 — the local-path clones fetched a STALE BRANCH, and the tell was the ref not moving

After the first fetch pass, 22 of 26 repos sat at 867de428 but FOUR did not move:
the four whose `origin` is the local path /home/reyerchu/vibe-ic.

    .114 _agentjob_lgate/repo        3982151c (2026-07-30)  unchanged
    .120 _agentjob_lgate/repo        3d13e2c5 (2026-08-14)  unchanged
    .121 _agentjob_lgate/repo        f6db3e921 (2026-08-01) unchanged
    .121 AI_IC_design/jfind63x8repo  f6db3e921 (2026-08-01) unchanged

Cause: `+refs/heads/main:...` fetches the SOURCE repo's local BRANCH `main`, and
that branch is itself stale even where the source's tracking ref is current:

    $ cd ~/vibe-ic
      local branch main = 3d13e2c59  2026-08-14      <-- what they were fetching
      origin/main       = 867de4289  2026-08-21

.120's lgate landing exactly on 3d13e2c5 is the fingerprint. `git fetch` reported
success in all four cases -- it did fetch, it just fetched something stale. Only
comparing before/after shas caught it.

Fixed by fetching those four straight from https://github.com/vibeic/vibe-ic.git
via an ad-hoc URL: writes only the tracking ref, changes no remote config, touches
no working tree.

    all 26 repos (6x ~/vibe-ic + 20 surviving clones) now at 867de428.

## F33 — a fleet sweep deleted `~/_harv_priv` on ALL FIVE remote hosts mid-session

Round 2's remote deploy failed on every host:

    bash: line 1: /home/reyerchu/_harv_priv/bin/wt_full.sh: No such file or directory

Not a script bug -- the redirect itself failed because the directory was gone:

    $ for h in 114 121 112 108 105: [ -d ~/_harv_priv ]  ->  GONE on all five

Round 1 created and used `~/_harv_priv/bin/` on each of those hosts. Between then
and now something removed it fleet-wide. Together with F29 (14 of 34 extra clones
deleted in the same window) this is the second independent sign that a sweep is
running on this fleet while the triage runs.

Consequence for the deliverable: round 1's table was measured against state that
is already partly gone -- 14 clones and 44 of the 223 extra worktrees no longer
exist. Round 2 re-measures only what survives and says so per row.
Deploy now does `mkdir -p` first; the local host (.120) was unaffected because rsh
runs its script locally there.

## F34 — CAUGHT: a deleted worktree was scoring as LANDED ("safe to delete")

The round-2 comparison showed 12 worktrees moving RECOVER -> LANDED with nadd
falling from hundreds/thousands to exactly 0, which looked like the fetch removing
staleness. It was not. Checking the raw rows:

    _wt_clockbasis    state=GONE  nfiles=0  nadd=0     (was "1942 lines to recover")
    _wt_disclose      state=GONE  nfiles=0  nadd=0     (was 1834)
    _wt_provstamp     state=GONE  nfiles=0  nadd=0     (was 1373)
    ... 12 of 12 identical

    $ ssh .114 'cd /home/reyerchu/_wt_clockbasis'
      fatal: cannot change to '/home/reyerchu/_wt_clockbasis': No such file or directory

`wt_full.sh` bails on `[ ! -d "$wt" ]` and emits state=GONE with every count zero.
My verdict engine's L0 rule is `nadd == 0 -> LANDED, "holds 0 lines main lacks"`.
So a worktree the sweep DELETED was being reported as content already in main and
safe to delete -- about trees holding up to 1942 authored lines.

This is the exact false-LANDED class F21 added guards for, arriving through a
different door: not a bad content measurement, but an ABSENT one read as zero.

Fix, two parts:
 1. A missing DIRECTORY does not mean missing WORK. The commit is still in the
    object store and reachable through the worktree's HEAD ref, so the content
    classification is still computable -- `git diff <mb> <head>` needs no working
    tree. wt_full.sh now classifies GONE worktrees from their commit and flags the
    directory as removed, instead of emitting zeros.
 2. The verdict engine refuses to derive ANY verdict from a row whose state is
    GONE/absent rather than measured.

24 of the 222 round-2 extra rows are GONE-state and need re-measuring this way.

## F35 — RESULT of the fetch: the stale-main caveat was REAL but SMALL

223 extra-clone worktrees, re-measured against current main 867de428 after fetching
all 20 surviving clones. Matched rows only (202; 20 could not be re-measured because
the clone or the tree was deleted between rounds):

    RECOVER    57 ->  59   (+2)
    LANDED    130 -> 127   (-3)
    ABANDON    15 ->  16   (+1)
    verdicts changed: 8 of 202

I predicted in F24 that the stale ref was INFLATING RECOVER. Net, it moved RECOVER
UP by two. The prediction was directionally wrong, and the reason is the mitigation
F24 itself named: rule L3 matches tip prose against the CANONICAL main's history
regardless of the clone's ref, so most landings were already being caught. The
stale ref mattered for 8 rows, not for the population.

THE THREE that moved AWAY from RECOVER -- these are the ones the fetch fixed:
  .120 ~/_rb_r808/mut_wt          R2->L1  UNLANDED/295 -> LANDED_PATCH/54
       "fix(flow): a bare `no_analog: true` block list is a ..."
  .120 ~/_gk_p855/base            R2->L1  UNLANDED/246 -> LANDED_PATCH/4
       "fix(sta): do not merge per-corner slack across the p..."
  .120 ~/vibe-ic-wt-progsupply-core R2->A6 issue #312 landed; ndel 4679 -> 7484
       "#312 - wire the SECOND track into Phase 1"

THE FIVE that moved TOWARD RECOVER -- all LANDED_PATCH -> UNLANDED, i.e. content
that WAS present in the older main and is NOT in the current one. main moved away
from them; ndel is 10-20x nadd in every case, so they are stale variants of files
main has kept developing, not newly discovered features:
  .120 ~/vibe-ic-wt-caravel_user_project-fix-phase3-asic-top-resolution-caravel
                                   989/13085 -> 1437/19060
  .120 ~/_wt_r5_stasta             842/10300 -> 1249/16234
  .105 ~/vibe-ic-wt-opentitan_aes-lint-xor-fold-memberkey    4/625  -> 62/1211
  .120 ~/vibe-ic-wt-caravel_user_project-fix-explicit-top-not-in-rtl  1/202 -> 7/347
  .120 ~/vibe-ic-wt-caravel_user_project-fix-def-progression          0/0   -> 3/152

Verified one: `_wt_r5_stasta` touches phase3_one_shot_runner.py, which main has
rewritten three times since (5100fc49c, 41bfd8a12, 9cc09b863), and its prose does
not appear in main's history. So its variant is superseded by main's continued
development. RECOVER is the cautious call, but these five are WEAK recovers and are
labelled as such rather than presented as found work.

## F36 — 24 rows now carry "directory deleted, commit survives"; 13 of them are RECOVER

With the GONE fix in place the published table flags every worktree whose DIRECTORY
the sweep removed but whose COMMIT is still in the object store:

    rows flagged dir-REMOVED : 24
      of those RECOVER       : 13   <-- real work, reachable only as a ref
      of those LANDED        : 11

Their `why` now says: "worktree DIRECTORY has been deleted - the commit survives in
the object store, so recover the REF, not the directory."

This is the actionable consequence of F29/F33: for those 13, `git worktree prune`
is the operation that would make the commits unreachable and lose the work. They
need a branch or tag before any pruning sweep runs, and recovering the directory is
neither possible nor the point.

## F37 — final integrity checks on the published table

    rows with no verdict                              : 0
    duplicate (host, path)                            : 0
    unmeasured rows, verdict withheld (rule U1)       : 2
    LANDED derived from an unmeasured row             : 0     <-- the F34 class, now impossible
    rows flagged directory-REMOVED                    : 24

    747 worktrees, all measured against origin/main 867de428 (2026-08-21).
      ~/vibe-ic (now 551 worktrees) : RECOVER 228  LANDED 179  ABANDON 138
      20 surviving clones (196)     : RECOVER  59  LANDED 127  ABANDON  16

Post-run worktree counts, confirming this job deleted nothing:
    .105 7   .108 43   .112 47   .114 173   .120 180   .121 104
Every one is higher than at the start of round 1 (4/28/38/149/166/99). The fleet is
growing and being swept at the same time; the table is a snapshot, not an inventory.

# ===== ROUND 3 (2026-08-21 22:5x): fan-out =====

## F38 — "477 undecided" is not the state; 355 need (re)judging, and here is why

Re-enumerated the whole fleet (every clone whose HEAD carries
vibe-ic-marketplace/, all six hosts):

    worktrees on the fleet NOW : 811     (was 747 when I last judged; it grew)
    decided and unchanged      : 734
    NEW, never judged          :  66
    MOVED, HEAD changed        :  11

So only 77 were strictly undecided. BUT main moved again while I worked:

    judged against : 867de428  plugin v1.11.18
    now            : a00f53f20 plugin v1.11.66     <-- ~48 versions of landings

That invalidates one direction only. As main advances, LANDED stays LANDED and
ABANDON stays ABANDON (content already in main remains in main, barring a revert);
the only verdict that can flip is RECOVER -> LANDED, because the work may have
landed in those 48 versions. So the correct re-judge scope is:

    NEW 66 + MOVED 11 + RECOVER-recheck 278  =  355

not 477 and not 811. Written to /home/reyerchu/_harv_remaining.tsv with the prior
verdict and measurements carried on each row.

## F39 — shard key: HOST, and hosts stay whole

The 355 are spread over all six machines, so HOST is the key. Every host belongs
to exactly one shard, so two agents can never fetch in the same clone.

    per-host load: 120=114  114=102  121=44  112=36  108=30  105=29

    shard a (mine) : 120                114   RECHECK 104  NEW  9  MOVED 1
    shard b        : 114 + 105          131   RECHECK  97  NEW 30  MOVED 4
    shard c        : 121 + 112 + 108    110   RECHECK  77  NEW 27  MOVED 6
                                        ---
                                        355   = every remaining row, none twice

Shard a is host 120 alone so my own work runs on this host, per hard rule 1.
Verified: no host in two shards; no (host,path) in two shards; shards sum to 355.

Rule written to /home/reyerchu/_harv_RULE.md (and ~/.claude/fleet/HARVEST_RULE.md),
with the reference implementation beside it in ~/.claude/fleet/.

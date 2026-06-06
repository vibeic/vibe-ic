---
name: core-agent-loop
description: Closed-loop core-agent that fixes plugin issues filed by the field-agent. Invoke as a cron prompt; the loop polls the repo for ANY OPEN non-PR issue (new OR reopened — no label gating, no comment classifier), reproduces and fixes the bug chip-AGNOSTIC-ally, SELF-VERIFIES (reproduce + run the full plugin test suite the CI way), bumps the patch version, pushes to main, posts a 繁體中文 fix comment in the canonical 5-section shape (incl 本機驗證 evidence), then `gh issue close` + adds the `core-closed` label. CLOSED is the terminal state; the field-agent audits closed issues on the real benchmark and reopens any it finds inadequate.
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill uses `IC-A / USB-HID tester /
> BENCH-A` as the canonical example chip — substitute your own IC
> name and host-tester name. The rules themselves are chip-AGNOSTIC
> and apply to any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic-d/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `IC-A` →
> `<your IC name>` and `USB-HID tester` → `<your host-tester name>`;
> the structural gates and rule bodies do not depend on those SKUs.

# Core-Agent Loop — Closed-Loop Plugin Issue Fixing

## Purpose

The core-agent is the **fix-verify-and-close** half of the Vibe-IC
quality loop. The field-agent (see `vibe-ic:field-agent-loop`) runs
the plugin against real benchmark IC projects, finds systematic
gaps, and files them as `ORGANIC:` GitHub issues. The core-agent
picks those up at every cron wake-up, ships a deterministic
chip-AGNOSTIC fix, **self-verifies** (reproduce + run the full
plugin test suite the CI way), then **closes** the issue and adds
the `core-closed` label. CLOSED is the terminal state. The
field-agent is the audit/reopen safety net: each cron tick it
re-checks closed `core-closed` issues on the REAL benchmark, marks
the good ones `field-verified` (stays closed), and `gh issue
reopen`s any it finds inadequate (which makes the issue actionable
to the core-agent again). This replaces the old
`wait-for-verification` limbo — that label is RETIRED.

The loop is **chip-AGNOSTIC**: fixes describe general plugin
behaviour (regex broadens, schema accepts more synonyms, gate
recognises canonical pattern); no fix references `IC-A`,
`BENCH-A`, `Vendor`, `usb_hid_tester`, `aid`, or any vendor IC name as
detection logic.

## The four-step loop

### Step 1 — poll

Run **before** any other action, deterministically:

```bash
python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py
```

The program lists every open non-PR issue as `actionable`. Exit
codes are the cron driver's signal:

| rc | Meaning | Core-agent action |
|----|---------|-------------------|
| 0  | No actionable issues | Output `(no actionable issues)` and exit this tick |
| 1  | ≥1 actionable | Process each issue listed |
| 2  | I/O / auth error | Log + exit; retry next tick (do NOT treat as actionable) |

No LLM classification, no label gating, no comment classifier. One
rule: **actionable = ANY open non-PR issue (new OR reopened).** A
reopened issue is just an open issue again, so the field-agent's
reopen automatically puts the issue back in front of the
core-agent — no special-casing. (`waiting` is always empty; the
key is retained in the report shape for backwards compatibility.)

### Step 2 — reproduce + fix

For each actionable issue:

1. `gh issue view <num>` (or curl + jq) to read body + comments.
2. Reproduce locally when possible. Programs live under:
   - `vibe-ic-marketplace/plugins/vibe-ic/programs/` (gates)
   - `vibe-ic-marketplace/plugins/vibe-ic/programs/phase*_one_shot_runner.py` (runners)
   - `tools/` (one-off helpers)
3. Write a chip-AGNOSTIC fix. This is the **one genuinely
   LLM step** in the loop — open-ended root-cause analysis +
   code authoring that cannot reduce to a regex/threshold. The
   chip-AGNOSTIC discipline itself, however, IS a deterministic
   gate: the forbidden-token scan (`IC-A`, `BENCH-A`, `Vendor`,
   `usb_hid_tester`, `aid`, etc.) is **enforced by
   `programs/source_chip_agnostic_check.py`** (deny-list sourced
   from `tests/chip_deny_list.txt`). Heuristics must use deny-list
   / length-floor / structural checks, not chip-class string
   literals; the fix must work across **every** benchmark chip.
4. Add tests covering BOTH the new path AND a regression-guard for
   the prior behaviour. Convention: `tests/test_v1_<MAJOR>_<MINOR>_<PATCH>_<slug>.py`.
5. **Self-verify** before closing. New-tests-green +
   full-suite-green ALONE is **insufficient** to close — that only
   proves the *intermediate products of the new code*, never that the
   defect the issue described is actually gone. Self-verification MUST,
   in this order:
   - **(5a) Execute the issue's `## 驗收` commands VERBATIM** against
     the issue-named defect artifact (or a faithfully reproduced
     fixture shaped like the issue's `現象`). Run the issue's
     acceptance command(s) exactly as written — the real program /
     gate invocation, not a unit-test paraphrase — and capture the
     **end-state output** (the gate verdict / exit-code / final line,
     not an intermediate file's mere existence). If the issue has NO
     `## 驗收` / acceptance section, say so explicitly with the
     `無驗收區` disclosure wording (see Step 4) and fall back to a
     reproduce-the-`現象` end-state instead.
   - **(5b)** Reproduce the original failing scenario and confirm it
     now passes.
   - **(5c)** Run the FULL plugin test suite the CI way (see Step 3 —
     both test trees, not a `-k`/single-file subset).
   The `本機驗證` section of the Step-4 close comment MUST quote
   **(a) the acceptance command text** (verbatim, in a code block) and
   **(b) its end-state output**, in addition to the `N/N PASS` suite
   line. Before posting, run the two deterministic gates (#478):
   ```bash
   python3 plugins/vibe-ic/programs/acceptance_evidence_in_fix_comment_check.py \
       --issue-number <num> <comment_file.md>     # exit 0 required
   python3 plugins/vibe-ic/programs/defect_artifact_fixture_check.py \
       --issue-number <num> <new_test_file.py>    # exit 0 required
   ```
   Closing is the core-agent's responsibility precisely because the
   core-agent self-verifies the acceptance criterion first; the
   field-agent is the downstream audit net.

   > **why_not_bucket_a (the judgment residual):** the *deterministic*
   > half — does the `本機驗證` section literally contain the issue's
   > acceptance command + an end-state line; does the regression test
   > load the named defect artifact and assert an end state — lives in
   > the two #478 programs above. The *reading-judgment* half stays
   > here: deciding whether a quoted command **truly IS** the
   > acceptance criterion (vs a superficially-similar command) and
   > whether its output has reached **end-state** (vs a misleading
   > intermediate) requires reading the issue for a novel defect, which
   > no regex can settle.

### Step 3 — push

```bash
# Bump patch version in BOTH locations:
#   plugins/vibe-ic/.claude-plugin/plugin.json     ("version": ...)
#   .claude-plugin/marketplace.json                 (.plugins[0].version)
# Version invariants are DETERMINISTIC gates, not prose:
#   - equality (plugin.json == marketplace.json)  -> enforced by
#     programs/marketplace_version_sync_check.py
#   - strict monotonic bump (new > previous commit) + equality re-assert
#     -> enforced by programs/version_bump_monotonic_check.py
#        (e.g. version_bump_monotonic_check.py --plugin-json <pj> \
#              --marketplace-json <mj> --base HEAD)

# Verify locally — HARD RULE: run the FULL suite (BOTH test trees), not a
# subset. A subset run once let a real regression onto main. That "did the
# agent run the full suite, not a -k/single-file subset" check is enforced by
# programs/full_suite_run_check.py (feed it the pytest command you ran).
# pytest.ini testpaths pins the trees:
( cd "$PLUGIN_ROOT" && python3 -m pytest -q )   # collects the full suite
python3 -m pytest -q mcp-eda-server/test        # if MCP server touched
# (added a program? -> programs/INDEX.md via tools/gen_programs_index.py;
#  added a skill? -> compliance.yaml + tests/test_compliance.py. The tests/ gates enforce both.)
bash tools/sync_opensource.sh --no-test     # mirror to opensource_repo/

# Commit ONLY the files you touched:
git add <specific files>
git commit -m "vX.Y.Z — for #<num> <one-line summary>"

# Push (NEVER --force, NEVER --no-verify — see §Hard prohibitions,
# enforced by programs/git_prohibition_guard.py):
git push origin main
```

### Step 4 — self-verify + CLOSE

Post a 繁體中文 fix comment on the issue. **5 mandatory sections
in this exact shape** (the `本機驗證` section carries the Step-2.5
self-verify evidence; the trailing line is the field-audit anchor).
The `本機驗證` section MUST carry an **acceptance-execution trace** —
it quotes the issue's `## 驗收` command(s) verbatim AND their
end-state output — not just an `N/N PASS` suite line:

```
Core agent 已推送修復：<commit_sha_short>

**問題**：<重述 field-agent 的問題>
**根因**：<root cause analysis>
**修法**：<chip-AGNOSTIC fix description + files changed>
**本機驗證**：
- 驗收指令（逐字執行 issue 的 `## 驗收`）：
  ```
  <issue 的 ## 驗收 指令原文>
  ```
- 端態輸出：
  ```
  <該指令的端態輸出，例如 gate 的最終 verdict / exit-code>
  ```
- 全測試套件（CI 方式，雙樹）：N/N PASS

Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field agent 複查若發現未完整，請 reopen 並補反證。
```

**No-acceptance-section case.** If the issue genuinely has no `##
驗收` / acceptance section, the `本機驗證` section MUST state
`無驗收區（issue 未提供 ## 驗收）` and instead quote the
reproduce-the-`現象` command + its end-state output. The
compliance gate accepts either the `驗收` trace OR the `無驗收區`
disclosure — but NOT a bare `N/N PASS` with neither.

Then **close** the issue and apply the `core-closed` label:

```bash
gh issue close <num>
gh issue edit <num> --add-label core-closed
# OR via curl:
curl -sH "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     -X POST https://api.github.com/repos/<owner>/<repo>/issues/<num>/labels \
     -d '{"labels":["core-closed"]}'
```

**CLOSE the issue after self-verify.** CLOSED is the terminal
state. The `core-closed` label marks the issue as a field-audit
target. Do NOT apply `wait-for-verification` (RETIRED) and do NOT
apply `field-verified` (that is the field-agent's marker). If the
field-agent's audit finds the fix inadequate it removes
`core-closed`, reopens the issue, and posts counter-evidence —
which makes the issue actionable to the core-agent again.

### STOP CONDITION

The cron continues indefinitely. The core-agent does **not**
self-terminate — it stays available to react to any future
field-agent filing. A tick that produces `(no actionable issues)`
is a healthy idle state, not a stop signal.

## Hard prohibitions (non-negotiable)

These are no longer prose-only — each is a DETERMINISTIC gate. Rules
1–4 are enforced by **`programs/git_prohibition_guard.py`** (feed it the
command strings before running them); rule 5 by
**`programs/source_chip_agnostic_check.py`**; rule 6 by
**`programs/field_agent_terminology_scan.py`** (feed it the comment /
external text before publishing).

| # | Rule | Reason | Enforced by |
|---|------|--------|-------------|
| 1 | NEVER `git push --force` (`--force-with-lease` is the safe sibling, allowed) | Loss of upstream history | `git_prohibition_guard.py` |
| 2 | NEVER `git reset --hard` on tracked branches | Loss of local work | `git_prohibition_guard.py` |
| 3 | NEVER `git commit --no-verify` | Bypasses pre-commit gates that catch chip-specific literals | `git_prohibition_guard.py` |
| 4 | NEVER `git checkout .` or similar discard | Loss of work-in-progress | `git_prohibition_guard.py` |
| 5 | NEVER use chip-specific string literals as detection logic | Fix must be general | `source_chip_agnostic_check.py` |
| 6 | Use term "field agent" (not "debug agent") in external text | Project terminology decided 2026-05-10 | `field_agent_terminology_scan.py` |

**Closing is REQUIRED, not forbidden.** The old "NEVER close a
GitHub issue" prohibition is REMOVED. Under the core<->field
backlog state machine the core-agent MUST `gh issue close` (and add
`core-closed`) after self-verifying its fix — CLOSED is the terminal
state. `gh issue close` / `gh issue reopen` are NOT flagged by
`git_prohibition_guard.py`. The field-agent's reopen, not a label
limbo, is the audit safety net.

## State

The core-agent is **stateless across cron ticks**. All state lives
in git (commit history, branch state) and GitHub (issue labels,
comments). Every tick is independent — no `state.json` file.

This is the inverse of the field-agent (which carries
`_field_agent_state.json`). The reason: core-agent reacts to one
issue at a time and the response is fully captured by the
open→closed transition (+ `core-closed` label). No multi-step LLM
dispatch to track.

## Cron-invocation template

```
Run /core-agent-loop against reyerchu/AI_IC_design.

Each tick must:
1. python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py
2. If rc=0 → output "(no actionable issues)" and exit.
3. If rc=1 → for each entry in `actionable[]`:
     a. Reproduce the bug from issue body + comments.
     b. Write a chip-AGNOSTIC fix + tests.
     c. Bump patch version (plugin.json + marketplace.json),
        commit (`vX.Y.Z — for #<num> <summary>`), push origin main
        (NO --force, NO --no-verify).
     d. Self-verify: FIRST execute the issue's `## 驗收` commands
        VERBATIM on the named defect artifact / reproduced fixture
        and capture the END-STATE output, THEN confirm the original
        failure now passes, THEN run the FULL plugin test suite the
        CI way; the `本機驗證` evidence MUST quote the acceptance
        command + its end-state output (not just `N/N PASS`). Run
        acceptance_evidence_in_fix_comment_check.py +
        defect_artifact_fixture_check.py (#478, exit 0 each) before
        posting.
     e. Post 繁體中文 fix comment in the canonical 5-section shape
        (see SKILL.md §Step 4), then `gh issue close` <num> and add
        label `core-closed`.
4. If rc=2 → log + exit. Retry next tick.

Hard prohibitions: see SKILL.md §Hard prohibitions.
End of tick.
```

Save as the CronCreate `prompt` field; pick a 4-minute interval.

## Compliance gate (mandatory)

After producing the 繁體中文 fix comment text (before posting),
save to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/core-agent-loop/compliance.yaml \
    <comment_file.md>
```

Exit 0 = PASS, exit 1 = FAIL with missing elements listed. Patch
and re-run until PASS, THEN post the comment.

## Reference

Deterministic gates backing this skill (the loop SCAFFOLD is fully
programmable; only Step 2 fix-authoring is genuine LLM judgment):

- Poll / actionability (every open non-PR issue): `programs/poll.py`
- Close-comment 5-section shape + acceptance-execution trace:
  `compliance.yaml` (+ `_shared/skill_compliance_check.py`)
- Acceptance-criterion executed + quoted in `本機驗證` (#478):
  `programs/acceptance_evidence_in_fix_comment_check.py`
- Regression test loads the named defect artifact + asserts end-state
  (#478): `programs/defect_artifact_fixture_check.py`
- Forbidden git/gh ops (prohibitions 1–4): `programs/git_prohibition_guard.py`
  (`gh issue close` / `gh issue reopen` are NOT flagged)
- Chip-AGNOSTIC source scan (prohibition 5): `programs/source_chip_agnostic_check.py`
- Terminology guard (prohibition 6): `programs/field_agent_terminology_scan.py`
- Version equality: `programs/marketplace_version_sync_check.py`
- Version strict-monotonic bump: `programs/version_bump_monotonic_check.py`
- Full-suite (not subset) pytest run: `programs/full_suite_run_check.py`
- Field-agent counterpart: `vibe-ic:field-agent-loop`

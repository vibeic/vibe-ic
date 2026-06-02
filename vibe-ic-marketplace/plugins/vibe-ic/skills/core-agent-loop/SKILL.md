---
name: core-agent-loop
description: Closed-loop core-agent that fixes plugin issues filed by the field-agent. Invoke as a cron prompt; the loop polls the repo for any OPEN non-PR issue without `wait-for-verification` label, reproduces and fixes the bug chip-AGNOSTIC-ally, bumps the patch version, pushes to main, posts a 繁體中文 fix comment in the canonical 5-section shape, and re-applies the `wait-for-verification` label. NEVER closes issues — verification is the field-agent's job.
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

The core-agent is the **fix-and-push** half of the Vibe-IC quality
loop. The field-agent (see `vibe-ic:field-agent-loop`) runs the
plugin against real benchmark IC projects, finds systematic gaps,
and files them as `ORGANIC:` GitHub issues. The core-agent picks
those up at every cron wake-up, ships a deterministic
chip-AGNOSTIC fix, hands back via the `wait-for-verification`
label, and waits for the field-agent to verify on real hardware.

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

The program lists every open non-PR issue partitioned into
`actionable` (no `wait-for-verification` label) vs `waiting`. Exit
codes are the cron driver's signal:

| rc | Meaning | Core-agent action |
|----|---------|-------------------|
| 0  | No actionable issues | Output `(no actionable issues)` and exit this tick |
| 1  | ≥1 actionable | Process each issue listed |
| 2  | I/O / auth error | Log + exit; retry next tick (do NOT treat as actionable) |

No LLM classification — the label state is the sole source of
truth. `NEW` / `FEEDBACK` / `WAITING` collapse into one rule:
**actionable iff `wait-for-verification` absent.**

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

### Step 4 — comment + label

Post a 繁體中文 fix comment on the issue. **5 mandatory sections
in this exact shape**:

```
Core agent 已推送修復：<commit_sha_short>

**問題**：<重述 field-agent 的問題>
**根因**：<root cause analysis>
**修法**：<chip-AGNOSTIC fix description + files changed>
**本機驗證**：<gates/tests run + result, e.g. "N/N PASS">

請 field agent 在實機 benchmark 驗證；通過請關閉此 issue，不通過請補留言。
```

Then apply the `wait-for-verification` label:

```bash
gh issue edit <num> --add-label wait-for-verification
# OR via curl:
curl -sH "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     -X POST https://api.github.com/repos/<owner>/<repo>/issues/<num>/labels \
     -d '{"labels":["wait-for-verification"]}'
```

**DO NOT close the issue.** Verification is the field-agent's
responsibility. The label is the hand-off signal.

### STOP CONDITION

The cron continues indefinitely. The core-agent does **not**
self-terminate — it stays available to react to any future
field-agent filing. A tick that produces `(no actionable issues)`
is a healthy idle state, not a stop signal.

## Hard prohibitions (non-negotiable)

These are no longer prose-only — each is a DETERMINISTIC gate. Rules
1–5 are enforced by **`programs/git_prohibition_guard.py`** (feed it the
command strings before running them); rule 6 by
**`programs/source_chip_agnostic_check.py`**; rule 7 by
**`programs/field_agent_terminology_scan.py`** (feed it the comment /
external text before publishing).

| # | Rule | Reason | Enforced by |
|---|------|--------|-------------|
| 1 | NEVER `git push --force` (`--force-with-lease` is the safe sibling, allowed) | Loss of upstream history | `git_prohibition_guard.py` |
| 2 | NEVER `git reset --hard` on tracked branches | Loss of local work | `git_prohibition_guard.py` |
| 3 | NEVER `git commit --no-verify` | Bypasses pre-commit gates that catch chip-specific literals | `git_prohibition_guard.py` |
| 4 | NEVER `git checkout .` or similar discard | Loss of work-in-progress | `git_prohibition_guard.py` |
| 5 | NEVER close a GitHub issue (`gh issue close`) | Verification belongs to field-agent | `git_prohibition_guard.py` |
| 6 | NEVER use chip-specific string literals as detection logic | Fix must be general | `source_chip_agnostic_check.py` |
| 7 | Use term "field agent" (not "debug agent") in external text | Project terminology decided 2026-05-10 | `field_agent_terminology_scan.py` |

## State

The core-agent is **stateless across cron ticks**. All state lives
in git (commit history, branch state) and GitHub (issue labels,
comments). Every tick is independent — no `state.json` file.

This is the inverse of the field-agent (which carries
`_field_agent_state.json`). The reason: core-agent reacts to one
issue at a time and the response is fully captured by the
label-state transition. No multi-step LLM dispatch to track.

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
     d. Post 繁體中文 fix comment in the canonical 5-section shape
        (see SKILL.md §Step 4).
     e. Apply label `wait-for-verification`.
     f. Do NOT close the issue.
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

- Poll / actionability partition: `programs/poll.py`
- Fix-comment 5-section shape: `compliance.yaml`
  (+ `_shared/skill_compliance_check.py`)
- Forbidden git/gh ops (prohibitions 1–5): `programs/git_prohibition_guard.py`
- Chip-AGNOSTIC source scan (prohibition 6): `programs/source_chip_agnostic_check.py`
- Terminology guard (prohibition 7): `programs/field_agent_terminology_scan.py`
- Version equality: `programs/marketplace_version_sync_check.py`
- Version strict-monotonic bump: `programs/version_bump_monotonic_check.py`
- Full-suite (not subset) pytest run: `programs/full_suite_run_check.py`
- Field-agent counterpart: `vibe-ic:field-agent-loop`
- Backwards-compat thin wrapper:
  `tools/core_agent/poll_open_issues.py` (re-exports `poll()`
  from `programs/poll.py` so legacy invocations still work)

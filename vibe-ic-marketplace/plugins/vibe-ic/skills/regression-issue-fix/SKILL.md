---
name: regression-issue-fix
description: Mandatory entry point for fixing any Phase 1 picker / extractor regression issue. Runs the intake check first, refuses to start a fix on issues that lack a verbatim input snippet / expected output / drop-in fixture. Closes the issue-#5 thrashing pattern (5 plugin releases instead of 1-2) by enforcing the productive form up front.
---

# Regression Issue Fix — Hard intake gate

## When to use

User asks: "fix issue #N" / "read and fix issue #N" / "address the
regression in issue #N" — for any GitHub issue that affects a
**Phase 1 per-doc auto-extractor**: `L1.ic_name`, `L6.fsm_states`,
`L4.regmap`, `L8.timing_waveform`, `L11.otp_content`, etc.

## Hard rule (non-negotiable)

**Step 1 is mandatory and runs BEFORE any code is read or edited.**
Skipping it reproduces the issue-#5 thrashing pattern.

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/regression_issue_intake_check.py \
    --issue-number <N> \
    --repo vibeic/vibe-ic
```

Three possible outcomes:

| Exit code | Meaning | Next action |
|---|---|---|
| 0 + fixture written | Issue meets template; fixture under `tests/phase1_fixtures/<project>/` | Step 2 |
| 0 + `--no-emit-fixture` | Validation only | Re-run without `--no-emit-fixture` to land the fixture |
| 1 | Issue is missing verbatim input / expected / actual / version | **STOP. Post a comment on the issue asking the verifier to fill the gaps using `.github/ISSUE_TEMPLATE/picker-or-extractor-regression.yml`. Do NOT start guessing.** |

The intake program's failure output names every missing field so
the verifier knows exactly what to add.

## Step 2 — Confirm the fixture FAILS on current code

Before writing any fix:

```bash
cd vibe-ic-marketplace/plugins/vibe-ic
python3 -m pytest tests/test_phase1_fixtures_regression.py -k <project> -v
```

The new fixture **must fail** (the picker returns the verifier's
reported `actual` value, not the `expected`). If the test passes
on current code, the issue is stale or already fixed — comment on
the issue and stop. Do not push a no-op release.

## Step 3 — Write the fix

Edit the picker / extractor in
`programs/phase1_one_shot_runner.py` (or the relevant L-doc
generator). Constraints:

* Run the **full fixture suite** after each iteration:
  `pytest tests/test_phase1_fixtures_regression.py`
* Any fixture that **flips** (was passing, now failing — or vice
  versa) is a real-input behaviour change. The `pre_commit_check.sh`
  picker-fixture-thrash guard will refuse the commit unless the
  message carries a matching `fixture-flip-acknowledged: <project>:
  <old> -> <new>` line.
* Add the new fixture's expected name to
  `tests/test_phase1_fixtures_regression.py::_EXPECTED` once the
  fix passes.

## Step 4 — Self-verify, push, close with `core-closed`

The core agent now SELF-VERIFIES and CLOSES the issue. Before
closing, run the FULL plugin test suite the CI way and reproduce
the original failure to confirm it is gone (the `本機驗證`
evidence below).

```bash
# 1) self-verify the CI way (reproduce + full suite)
python3 -m pytest tests/test_phase1_fixtures_regression.py -k <project> -v
cd vibe-ic-marketplace/plugins/vibe-ic && python3 -m pytest   # full suite

# 2) push the chip-AGNOSTIC fix + version bump
git push origin main

# 3) close + tag core-closed (the field-audit target marker)
gh issue close <N> --repo vibeic/vibe-ic
gh issue edit <N> --repo vibeic/vibe-ic --add-label core-closed
```

Post a 繁體中文 close comment in the canonical 5-section shape
(see below), then close + add the `core-closed` label.

**New backlog lifecycle** (replaces the retired
`wait-for-verification` limbo): the default terminal state of a
fixed issue is CLOSED with `core-closed`. The field agent audits
CLOSED `core-closed` issues against the real benchmark every tick
— on success it adds `field-verified` (terminal); if the fix is
inadequate it `gh issue reopen`s, removes `core-closed`, and posts
counter-evidence, putting the issue back in the core agent's queue.

`wait-for-verification` is RETIRED — never apply, poll, or
cross-check it.

### Core close-comment shape (5 sections, 繁體中文)

```
Core agent 已推送修復：<sha>
**問題**：<重述 field-agent 的問題>
**根因**：<root cause>
**修法**：<chip-AGNOSTIC fix + files>
**本機驗證**：<gates/tests run + result, e.g. N/N PASS>
Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field agent 複查若發現未完整，請 reopen 並補反證。
```

## What this skill enforces

1. **Verbatim input or no fix.** Issues that omit the input
   snippet are bounced back to the verifier with a templated
   ask. No guessing rounds.
2. **Fixture lands first, fix lands second.** A regression that
   doesn't reproduce in `tests/phase1_fixtures/` cannot be
   fixed reliably; the fixture is part of the issue, not a
   downstream artefact.
3. **No silent thrash.** The pre-commit guard refuses fixture
   `_EXPECTED` flips without explicit acknowledgment.
4. **Self-verify then close with `core-closed`.** The core agent
   self-verifies (reproduce + full CI suite) and closes the issue,
   tagging `core-closed`. The field-agent's real-benchmark audit is
   the safety net: it adds `field-verified` on success or `gh issue
   reopen`s (removing `core-closed`) with counter-evidence on
   failure. `wait-for-verification` is retired.

## Cross-references

* Issue template: `.github/ISSUE_TEMPLATE/picker-or-extractor-regression.yml`
* Intake program: `programs/regression_issue_intake_check.py`
* Thrash guard: `programs/picker_fixture_thrash_guard.py` (wired
  into `tools/ci/pre_commit_check.sh`)
* Fixture suite: `tests/phase1_fixtures/` +
  `tests/test_phase1_fixtures_regression.py`
* Sibling skill (general bug→backlog): `skills/community-backlog-submit`

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff
lines, tool invocations.

**Your task is not complete until the audit returns PASS.**

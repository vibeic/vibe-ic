---
name: community-backlog-submit
description: Record a general (IC-agnostic) backlog item from the current design session. Use when the agent encounters a bug, issue, or enhancement opportunity in the plugin or MCP tools. Invoke at any point during Phase 1/2/3 when you discover a gap.
---

# Community Backlog Submit — Organic Plugin Contribution

## Purpose

When a bug is found in the generated RTL (via simulation, hardware test,
or manual review), the agent's job is NOT to just fix the bug — it must
also **look back at the plugin** and ask:

> "Could the current plugin have caught this bug BEFORE it reached
> hardware?  If not, what general enhancement would catch this
> entire CLASS of bugs in the future?"

This skill records that **enhancement opportunity** — not the bug
itself — as a structured, IC-agnostic backlog item that can be
contributed back to the Vibe-IC community.

> **Where this fits — the public contribution model (Layer 1).** A **backlog** is
> the *report-only* half of Vibe-IC's public contribution model: you found a gap
> but are not carrying a fix. The other half is a **PR** (report-with-fix). Both
> are valid; the merged **repo-gatekeeper / maintainer** triages backlogs and
> reviews + lands PRs into the next plugin version. (The maintainer's own in-house
> fixes land by direct push — that internal shortcut is not the contributor path;
> as a contributor you file a **backlog** or a **PR**, you do not push to `main`.)

## The fix-all-into-the-plugin principle

> When you report a backlog / find an issue, the expectation is **NOT** to triage it into a
> category and then decide whether it is "worth" fixing. **Every issue gets fixed, and the fix
> lands in the next version of the vibe-ic plugin** — it does not matter whether the fix lives in
> a deterministic program, an MCP tool, or a skill. The category is an implementation detail of
> *where* the fix goes, never a reason to *skip* the fix.
>
> - Do **not** discard an issue as "not a plugin gap", "design-side", "clean-room variance",
>   "spec ambiguity", or "the author should have known". If a fresh user could hit it, the plugin
>   must handle it next time.
> - A recovery that currently relies on a **skill-prose lesson** a fresh author might forget is
>   itself an enhancement: **promote it to a deterministic program** (program-first) so it fires
>   every time, automatically.
> - The honest discard bucket is reserved **only** for a fix that is genuinely non-generalizable
>   (it would over-fit one design's quirk or peek at a hidden oracle) — and even then you record
>   *why*, you do not silently drop it.
>
> **Convergence test (loop-until-dry):** a benchmark / flow close-loop has converged only when a
> **fresh clean-room re-run on the newest plugin produces 0 residual that needs a plugin fix**.
> As long as a clean-room run still surfaces any recoverable residual, the loop is not done:
> capture it → fix it into the plugin → re-run. One round with zero new backlog is a candidate;
> two consecutive zero-backlog clean-room rounds is convergence.

This is why both halves below matter: the **bug** still gets fixed on the design side, AND the
**enhancement** is what makes the plugin catch the whole class next time — neither half is skipped.

### The key distinction

| Record this (enhancement) | Do NOT record this (bug — but STILL fix it design-side) |
|---------------------------|--------------------------|
| "Plugin lacks a gate for protocols where CRC init/update happen on the same cycle" | "Our IC's CRC output is wrong because crc_init and crc_update overlap" |
| "No program checks that wake signals have ≥2 clear paths" | "Wake register only clears on rst_n, missing soft-reset" |
| "The flow doesn't enforce WARN resolution before shipping" | "Agent ignored a WARN and shipped broken RTL" |

The right column is **not** a discard column — that bug is still fixed in the design. The left
column is the general plugin capability that makes the plugin catch the entire class next time.
The backlog answers: **"What general plugin capability, if added, would
prevent this entire class of bugs from reaching hardware?"**

## The generality rule (NON-NEGOTIABLE)

Every backlog item MUST describe a **general capability gap**, not a
specific IC's bug.  Before writing, ask yourself:

> "Would an agent designing a COMPLETELY DIFFERENT IC hit the same gap?"

If yes → record it.  If no → it's a project-specific issue, not a plugin gap.

### What to strip

| Remove | Replace with |
|--------|-------------|
| Chip names (IC-A, BME280, ...) | "a cable-side ID IC" / "an I2C sensor" / "a UART bridge" |
| Vendor names (Apple, Maxim, ...) | "the vendor" / omit entirely |
| Proprietary register maps | "the IC's register map" |
| OTP hex dumps | "OTP content" |
| Vendor PDF filenames | "the vendor datasheet" |
| Local file paths | omit |
| Tester SKUs (USB-HID tester) | "the protocol tester" / "the hardware tester" |
| Hard-coded command bytes | "the tester's connect command" |

### Examples

**Bad** (specific):
> "IC-A's wake register only clears on rst_n, missing the 80µs
> bus-LOW soft-reset path from Apple Lightning spec page 47."

**Good** (general):
> "Plugin lacks a gate for protocols where the wake-clear signal has
> only one reset path. Any protocol with multiple wake-clearing stimuli
> (soft reset, timeout, brownout) will fail the hardware test if only
> power-on reset is implemented."

## Procedure

### Step 1 — Root-cause review (the critical step)

After fixing a bug in the RTL, stop and review the current plugin:

1. **List all gate programs** that SHOULD have caught this bug class.
2. **Run each** against the buggy RTL (before your fix) — did any fire?
3. **If none fired**: this is a plugin gap.  A new gate or enhancement
   is needed.  Record it.
4. **If one fired but as WARN**: the gate detected it but severity was
   too low.  Record a severity-escalation enhancement.
5. **If one fired as ERROR and the agent ignored it**: this is an agent
   contract issue, not a plugin gap.  Record it only if the flow
   doesn't enforce the gate.

Classify the enhancement:

| Type | When to use |
|------|-------------|
| `bug` | A gate program produces incorrect output (false positive/negative) |
| `issue` | A gate exists but the flow doesn't enforce it properly |
| `enhancement` | No gate exists for this class of bugs — a new one is needed |

### Step 2 — Generalize

Strip all IC-specific details.  Describe the **pattern**, not the case.
Name the **component** using the format:

- `skill:<skill-name>` (e.g., `skill:control-logic-gen`)
- `program:<program-name>` (e.g., `program:crc_engine_isolation_check`)
- `mcp:<tool-name>` (e.g., `mcp:eda_synth`)
- `flow:<step-number>` (e.g., `flow:step-02`)

### Step 3 — Write the YAML

> **Scope of the YAML-mirror convention (ORGANIC #540).** The
> `community/backlogs/` YAML mirror is REQUIRED only for backlogs that
> originate **locally** and cross the trust boundary on their way to
> GitHub — i.e. records emitted by the capture skill
> (`benchmark-enhancement-capture` Bucket C) or authored by this skill's
> Step 3-4 path, where the YAML file IS the sanitize-gate artifact.
> Issues the field agent files **directly on GitHub as structured
> Markdown forms** are themselves the canonical, auditable record — they
> need NO retroactive YAML mirror, and backfilling one would create a
> second source of truth that can drift. One rule: *the record is
> canonical where it was born; a mirror is only required when a local
> file is what gets published.*

Create a file in `community/backlogs/` named `ORGANIC-<YYYYMMDD>-<short_desc>.yaml`:

> **`plugin_version` is a measurement, not a decoration (#795).** Read it from
> `.claude-plugin/plugin.json` — the shipped value, at the moment you file. Do
> NOT copy the placeholder below and do NOT reuse a version you saw in another
> backlog: a maintainer dates a finding by that line, so a stale one makes a
> live finding read as archaeology and is a reasonable thing to close unread.
> The placeholder is deliberately not a version, so Step 4's sanitize gate
> names the field if you forget. (Records emitted by
> `benchmark-enhancement-capture` get this filled in for you.)

```yaml
type: enhancement
severity: P1
component: program:pre_awake_silence_check
plugin_version: "<read from .claude-plugin/plugin.json>"

title: >-
  Gate should escalate to ERROR when protocol has multiple wake-clearing
  stimuli but RTL only implements one

pattern: |
  When a serial protocol defines multiple wake-clearing stimuli
  (power-on reset, soft reset, timeout, brownout), the plugin's wake
  gate only emits WARN for single-clear-path RTL. The agent treats
  WARN as PASS and ships without fixing. This is a known-broken
  implementation that will fail any hardware test toggling a non-reset
  wake-clear stimulus.

suggested_fix: |
  Escalate SINGLE_CLEAR_PATH from WARN to ERROR. A protocol with a
  wake state inherently requires multiple clear paths; a single clear
  path is not "advisory" — it's broken.

id: "ORGANIC-20260427-wake-clear-escalate"
submitted_at: "2026-04-27T14:30:00+08:00"
session_context: "Fresh-agent Phase 2+3 run; agent ignored WARN and shipped"
```

> **What `pattern` must say — the rule the example above is only one
> instance of.** A `pattern` states the **class** of defect: what shape of
> input meets what shape of handling, and what wrong outcome follows. Write
> it so a reader can use it to recognise a **different** instance — a case
> you have not seen, in a different design, at a different step. It is NOT a
> restatement of `title` (the title names this occurrence; the pattern names
> the family it belongs to) and it is NOT a description of this one symptom.
> Test it before you write it down: *if this sentence only fits the record it
> sits on, it is not a pattern* — it cannot match the next occurrence, which
> is the only thing the field is for.
>
> Do not imitate the shape of the example above without meeting that rule,
> and never paste a `pattern` in from another record or from an issue body: a
> pattern that came from a different defect is worse than an empty one,
> because it reads as measured, and Step 4's gate — which only checks that
> the field is non-empty — will pass it.

### Step 4 — Sanitize

Run the sanitization gate:

```bash
python3 plugins/vibe-ic/programs/backlog_sanitize_check.py \
    --file community/backlogs/ORGANIC-<your_file>.yaml
```

- Exit 0 → clean, ready to submit
- Exit 1 → specificity violations found; fix the flagged fields
- Exit 2 → file parse error

Fix any ERROR findings before proceeding.  WARN findings should be
reviewed — they may be false positives for genuinely general content.

### Step 4.5 — Snapshot the defect artifacts (when you cite run-dir files)

If your backlog item cites **live run-dir files** as the defect evidence
(a truncated report, a failing log, a malformed JSON the runner produced),
**freeze them at filing time**. Run dirs evolve between filing and
verification — a healthy rerun can replace the very file you cited, so a
verifier dereferencing the live path later sees a *different* file and the
defect "disappears". The snapshot helper copies each cited artifact, byte
for byte, into an immutable capture archive
(`<repo-root>/community/captures/<slug>/` + a `manifest.json` recording the
source path, sha256, the filesystem mtime, and the issue ref).

1. **Name the artifacts** — list the exact run-dir paths your 現象 /
   證據區 cites.
2. **Run the snapshot helper**:
   ```bash
   python3 <plugin_root>/programs/defect_artifact_snapshot.py \
       --issue <issue-number> --slug <short-slug> \
       --artifact <run-dir/path/to/cited/file> \
       [--artifact <another/cited/file> ...]
   ```
   Exit 0 = every artifact frozen; exit 1 = a source was missing /
   unreadable (fix the path and re-run); exit 2 = usage. It prints, per
   artifact, **both** the `snapshot:` path and the `live:` path.
3. **Paste BOTH paths into the issue 證據區** — the immutable
   `snapshot:` path (the verifier's source of truth) AND the original
   `live:` path (for context). When the body names both, the downstream
   `defect_artifact_fixture_check` resolves the **snapshot** (re-verifying
   its sha256 against the manifest), so the fix verdict no longer depends
   on the mutated live file.

Skip this step only when your evidence is inline text / a synthetic
fixture (no live run-dir file is being cited).

4. **Lint the draft body BEFORE `gh issue create`** (flow #489 — the
   deterministic filing-time hook for ORGANIC-form issues):
   ```bash
   python3 <plugin_root>/programs/organic_issue_body_lint.py <draft.md>
   ```
   Named findings: `MISSING_ACCEPTANCE` (no `## 驗收` section),
   `ACCEPTANCE_NARRATIVE_ONLY` (no fenced executable command — the
   acceptance-evidence gate cannot bite, flow #485),
   `NO_DEFECT_ARTIFACT` (no path-like artifact named — see the snapshot
   step above). Exit 0 with warnings is advisory; fix the draft until
   PASS (or use `--strict` in automation). Reuses the same extractors as
   the gate-side check, so the grammar cannot drift.

### Step 5 — Submit (optional, with user consent)

Ask the user if they want to contribute this backlog to the community:

> "I found a general plugin gap during this session. Would you like to
> submit it as a community backlog to help improve the plugin for
> everyone? The submission contains no vendor or IC-specific data."

If the user agrees:

```bash
gh issue create --repo vibeic/vibe-ic \
    --title "ORGANIC: <title from YAML>" \
    --body "$(cat community/backlogs/ORGANIC-<file>.yaml)" \
    --label organic-backlog
```

If the user declines, the YAML file stays local — no data leaves.

### Step 6 — Inside the vibe-ic repo: COMMIT it, or DELETE it (ORGANIC #794)

Steps 1-5 create a file and never put it in git. That gap cost thirteen
ORGANIC items written into `vibe-ic-marketplace/community/backlogs/` between
2026-06-14 and 2026-07-12: they sat untracked beside twenty-five committed
siblings, indistinguishable in `ls`, until the working tree that held them was
cleaned and they were gone. Nobody can now say from the files which of the
thirteen were still live.

So when the backlogs directory you wrote into is **inside a git repository**,
the file has exactly two honest end states:

* **committed** — `git add <the file> && git commit` (explicit path; never
  `git add -A`), or
* **deleted** — you decided it was not worth filing, so remove it.

"Left on disk, untracked" is neither, and it is the state that loses items.

This is not left to memory: `repo_hygiene_gates.sh` runs

```bash
python3 <plugin_root>/programs/backlog_sanitize_check.py \
    --dir vibe-ic-marketplace/community/backlogs --audit tracked
```

on every landing, and it FAILs (rc 1) naming any backlog YAML on disk that git
does not track — or that a `.gitignore` rule hides. Run it yourself before you
hand off; it prints the count it examined either way.

> The rule is scoped to a git work tree. An end user filing a backlog in a
> non-repo directory is untouched: the gate REFUSES (rc 2) rather than
> pretending to have an opinion about a tree git cannot see.

## Do not

- **Do not include ANY vendor/IC-specific data** in the backlog.
- **Do not auto-submit** without asking the user first.
- **Do not skip the sanitize check** — it's the trust boundary.
- **Do not record project-specific workarounds** — only general gaps.
- **Do not fabricate gaps** — only record issues you actually encountered.

## Output

The skill produces:
1. A YAML file in `community/backlogs/ORGANIC-<id>.yaml`
2. A sanitization report from `backlog_sanitize_check`
3. (Optional) A GitHub Issue URL if the user consents to submission
4. Inside a git repo: that YAML **committed or deleted** — proven by
   `backlog_sanitize_check.py --dir <backlogs_dir> --audit tracked` (#794)

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/community-backlog-submit/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

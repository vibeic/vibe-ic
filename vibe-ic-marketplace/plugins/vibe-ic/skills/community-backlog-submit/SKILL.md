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

### The key distinction

| Record this (enhancement) | Do NOT record this (bug) |
|---------------------------|--------------------------|
| "Plugin lacks a gate for protocols where CRC init/update happen on the same cycle" | "Our IC's CRC output is wrong because crc_init and crc_update overlap" |
| "No program checks that wake signals have ≥2 clear paths" | "Wake register only clears on rst_n, missing soft-reset" |
| "The flow doesn't enforce WARN resolution before shipping" | "Agent ignored a WARN and shipped broken RTL" |

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

Create a file in `community/backlogs/` named `ORGANIC-<YYYYMMDD>-<short_desc>.yaml`:

```yaml
type: enhancement
severity: P1
component: program:pre_awake_silence_check
plugin_version: "0.101"

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

### Step 4 — Sanitize

Run the sanitization gate:

```bash
python3 plugins/vibe-ic-d/programs/backlog_sanitize_check.py \
    --file community/backlogs/ORGANIC-<your_file>.yaml
```

- Exit 0 → clean, ready to submit
- Exit 1 → specificity violations found; fix the flagged fields
- Exit 2 → file parse error

Fix any ERROR findings before proceeding.  WARN findings should be
reviewed — they may be false positives for genuinely general content.

### Step 5 — Submit (optional, with user consent)

Ask the user if they want to contribute this backlog to the community:

> "I found a general plugin gap during this session. Would you like to
> submit it as a community backlog to help improve the plugin for
> everyone? The submission contains no vendor or IC-specific data."

If the user agrees:

```bash
gh issue create --repo reyerchu/AI_IC_design \
    --title "ORGANIC: <title from YAML>" \
    --body "$(cat community/backlogs/ORGANIC-<file>.yaml)" \
    --label organic-backlog
```

If the user declines, the YAML file stays local — no data leaves.

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

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/community-backlog-submit/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

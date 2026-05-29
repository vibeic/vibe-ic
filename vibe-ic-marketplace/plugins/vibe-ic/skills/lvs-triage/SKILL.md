---
name: lvs-triage
description: Triage Layout-vs-Schematic (LVS) mismatches — missing connections, short/open nets, device parameter mismatches, unmatched instances. Use when the user says "LVS", "layout vs schematic", "LVS mismatch", "netlist compare", "Calibre LVS", "Netgen".
---

# LVS Triage

LVS proves that the drawn layout corresponds to the schematic / netlist. Mismatches are common in early iterations. This skill reads LVS reports (Calibre, Netgen, Pegasus) and proposes focused fixes.

## When to use

- After routing / layout finalization
- After any manual layout edit
- Before tapeout sign-off
- When integrating analog macros into a digital floorplan

## Inputs

1. LVS report file (Calibre `.rep`, Netgen `comp.out`, etc.)
2. Schematic netlist (`.cdl` / `.sp` / `.v`)
3. Extracted layout netlist
4. Device model list (PDK-specific)

## Workflow

1. **Parse report** into categories:
   - Unmatched instances
   - Unmatched nets (shorts, opens)
   - Device parameter mismatches (W/L, M, NF)
   - Property mismatches (labels, dummies)
2. **Top-3 root-cause check**:
   - Missing label on a net (most common)
   - Missing via between metal layers
   - Wrong device variant picked from PDK
3. **For each mismatch** propose the exact layer + coordinate to edit
4. **Batch waivers**: some analog dummies intentionally don't appear in schematic — document waiver
5. **Re-run plan**: minimal LVS subset to re-verify

## Output format

- `lvs/lvs_triage.md`:
  - Mismatch summary (count by category)
  - Top 20 mismatches with fix
  - Waiver list with justification
  - Re-run script

## Technical basis

LVS methodology references: Mentor Calibre user guide, open-source Netgen (http://opencircuitdesign.com/netgen/). Signoff tools: Calibre LVS, Cadence Pegasus, Synopsys IC Validator.

## Handoff

- Re-run DRC after LVS fix → `/drc-fix`
- Layout edits → documented in `/eco-plan` log
- Schematic change → back to `/rtl-repair` or `/analog-layout`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/lvs-triage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

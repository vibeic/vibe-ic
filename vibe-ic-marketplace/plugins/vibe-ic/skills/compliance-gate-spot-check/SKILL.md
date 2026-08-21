---
name: compliance-gate-spot-check
description: After flow_compliance_check.py reports Overall=PASS, AI spot-checks a sample of gates for false-PASS / gameable patterns. Triggers automatically when /vibe-ic-phase2/3/23/all returns PASS, before claiming tapeout-ready.
tier: verification
paired_program: flow_compliance_check.py
---

# Compliance Gate Spot-Check

**Purpose**: 77+ structural-RTL gates may report PASS but include gameable patterns where:
- Gate's regex is too narrow (Wave-30/33 have history of this — `slave_tx_no_device_break_check` originally missed `tx_oe_low` because `\b` boundary)
- Project carries a waiver that satisfies the gate but the underlying defect is real
- The gate's PASS condition is satisfied trivially (e.g. "L9 has ≥3 typed fields" satisfied by stub fields)

## Prioritize the sampling budget (optional — falls back to uniform sampling)

Before sampling, ask the **gate-reliability register** which gates have a history
of being gamed / false-passed, so the limited spot-check budget lands on the
historically-dangerous gates first instead of uniformly across all 77. The
register is `programs/gate_reliability_register.py` — a self-calibrating
per-gate EMA ledger of pass-rate and **false-PASS-rate**. It is an *optional
prioritizer*: when the ledger is empty/absent it ranks nothing, and you fall
back to the uniform "5 random gates" behavior in step 1 below.

The ledger path is positional (the program calls it `LEDGER`). Use a stable
location such as `<project>/reports/gate_reliability_register.json` (or a
shared cross-project ledger). Steps:

1a. **Ensure the ledger exists, then rank.** A freshly `touch`ed (empty) ledger
    ranks to `[]` and you proceed uniformly — so this never blocks you:

    ```bash
    # create on first use so `rank` never errors on a missing file
    touch <project>/reports/gate_reliability_register.json

    # priority-ordered gate list (highest false-PASS history first)
    python3 programs/gate_reliability_register.py rank \
        <project>/reports/gate_reliability_register.json --top 10
    ```

    The output is a JSON array of `{"gate": ..., "spotcheck_priority": ...}`
    sorted highest-priority first. **Spend your sampling budget on the
    top-ranked gates** (they are the historically-gamed ones) before sampling
    the remaining gates at random. If the array is empty, sample uniformly.

## Verification checklist

1. **Sample 5 PASS gates** — drawn from the register `rank` output above
   (top-ranked first; fill the rest at random from the 77 list). For each:
   - Open the gate's `*_check.py` source
   - Read the PASS condition logic
   - Open the project's relevant artifact the gate inspects
   - Manually verify the artifact actually satisfies the gate's INTENT, not just its REGEX

2. **Waiver scan**: the deterministic half is enforced by
   `programs/waivers_schema_check.py` (reason length ≥ `MIN_REASON_LEN`
   chars + placeholder rejection + `review_required` + linked-ticket
   presence + no-stacking via `cascades_to` per-target accountability)
   and `programs/waiver_legitimacy_check.py` (boilerplate / lazy-reason
   anti-pattern detection). Run both instead of eyeballing the
   numeric/boolean rules:

   ```bash
   python3 programs/waivers_schema_check.py <project> --strict-review-required --strict-ids
   python3 programs/waiver_legitimacy_check.py <project> --strict
   ```

   `--strict-ids` (#526) is what makes "this waiver names a step that does
   not exist" a nonzero exit HERE. It is off by default because the same
   findings are consumed by `flow_compliance_check`, which turns any schema
   error into `SystemExit(1)` — an inert waiver must cost the reader one
   warning line, not the entire compliance report. Standalone, the exit code
   is the whole signal, so ask for it.

   The only residual judgment left to you: is each rationale *substantive
   and correct* (vs. plausible-but-wrong)? Read the rationale against the
   underlying defect; the programs cannot tell a true reason from a
   well-formed false one.

3. **Gameability scan** — the three literal token / structural
   anti-patterns are enforced by `programs/gameable_placeholder_scan.py`
   (raw `__TODO__` / `<unknown>` strings in any `generated_docs/L*.json`;
   gen-time `aliases` equal to `name.lower()` / `name.replace("_","")`;
   `expected_verdict_byte_hex` literal `0x__todo__`). Run it instead of
   grepping by hand (it FAILs honestly on a project with no generated
   docs rather than vacuous-passing):

   ```bash
   python3 programs/gameable_placeholder_scan.py <project>
   ```

   The two remaining gameability patterns genuinely need an LLM and stay
   here:
   - Sim transcript with copy-pasted `BR_PULSE / rx_byte / TX_RESP` tokens not actually exercised
   - Reference TB scenarios that always print PASS regardless of input

4. **Deep dive on critical gates**:
   - `phase1_doc_content_implementation_completeness_check` — confirm citations are real, not just file:line tokens that happen to appear
   - `assertion_covers_l3_constraints_check` — open rtl/assertions.sv, count actual `assert property` clauses, confirm each cites a real L3 constraint
   - `bit_level_full_stack_tb_oracle_check` — open sim_full_stack/results.json, confirm per_vector entries are real bit captures not synthesized stubs

5. **Cross-gate consistency**:
   - If `protocol_reference_tb_pass_check=PASS` and `bit_level_full_stack_tb_oracle_check=PASS`, the per_vector data should match scenarios in reference TB transcript
   - If `flow_compliance_check Overall=PASS` and any individual gate=FAIL, that's a contradiction → investigate

## Record outcomes back to the register (so the ledger learns)

After spot-checking each sampled gate, write its outcome back so future
spot-checks re-prioritize. This is **additive** — it only updates the EMA
ledger and never changes any gate's own pass/fail logic. For each gate you
inspected:

- Gate held up under inspection → record a clean PASS:

  ```bash
  python3 programs/gate_reliability_register.py record \
      <project>/reports/gate_reliability_register.json \
      --gate <gate_name> --pass
  ```

- Gate reported PASS but you proved the design was actually wrong
  (gameable pattern, trivial satisfier, stale waiver) → record a **false PASS**
  so it floats to the top next time:

  ```bash
  python3 programs/gate_reliability_register.py record \
      <project>/reports/gate_reliability_register.json \
      --gate <gate_name> --pass --false-pass
  ```

- Gate legitimately FAILed → record a fail (`--fail`; `--false-pass` is
  rejected with `--fail`).

Optionally dump the updated ledger with
`python3 programs/gate_reliability_register.py report <ledger>`.

## Spot-check actions

- Pick the `--strict-structural` summary line listing 0 FAILs, but identify gates that are technically WIRED_VIA_TEST_ONLY (they ran but their logic isn't covered)
- For 3 random gates, write a tiny pytest that intentionally violates the invariant the gate is supposed to catch; confirm the gate would FAIL on that input.

## When to escalate

- Any gameable pattern found → re-run runner after patching
- Waiver lacks substantive rationale → reject and request real evidence
- Gate regex appears too narrow → file gate-improvement issue, propose tightening

## Output

Append findings to `<project>/reports/compliance_spot_check.md`.

This skill is the LAST line of defense before claiming tapeout-ready. Skip with caution.


## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit.


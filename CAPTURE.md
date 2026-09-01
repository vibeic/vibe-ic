# CAPTURE — u_hawaii_adc v1.15.30 round 4

## Summary

Three general flow recoveries were distilled from the real acceptance run into
the local branch. `LAND.md` contains the landing checklist and the complete
three-justification matrix.

| Candidate | Prior failure | General rule | Route |
|---|---|---|---|
| Explicit applicability for delay/threshold gates | P0 gained `warn_acceptance_policy_check` from two absent-condition warnings | Only typed design declarations may produce `SKIPPED-CONDITION`; undeclared absence remains WARN | producer programs + flow command wiring |
| Technology-generic netlist discrimination | Step 9 treated escaped Yosys internal cells as zero cells, then PDK mismatch | Parse escaped identifiers; generic-only is typed rc=2 N/A, while empty/mixed/wrong-PDK remain FAIL | `pdk_consistency_check.py` |
| Pre-audit stage-analog report production | Step 14's final judge was the first writer, so the output was `audit_created` | Top runner produces the scoped stage report after analog execution and before step-view/final audit | `vibe_ic_one_shot_runner.py` |

## Evidence

- Pre-fix negative control: 6 failed; substantive-control audit graded 5 as
  observed-value failures.
- Post-fix focused: 41 passed.
- Adjacent runner/advisory/taxonomy/policy: 72 passed.
- Corpus sweep: 89 projects, 178 warning-check invocations, 0 false positives,
  140 explicit-declaration transitions.
- Real candidate replay: P0 warning subgate removed; PDK advisory records rc=2
  `VACUOUS_PASS`/`DESIGN_DECLARED_NA`; Step 14 required outputs become 2/2
  step-attributed. Real analog blockers remain FAIL.
- Full plugin suite: INCOMPLETE at 18%, no terminal rc/JUnit; no PASS or outer
  failure set is claimed.

## Discards

Step 4 and A2–A4 were not captured as defects. Their missing analog oracle,
delta-sigma topology, design-bound sizing, and downstream PVT evidence are
legitimate unattended-runtime capability/upstream gaps, not absent conditions
and not external dependencies. Step 9's remaining `chip_area` result is likewise
INCOMPLETE until technology mapping supplies a measurement. Step 14 remains
FAIL because its produced report honestly contains those analog failures.

No push, PR, landing, version bump, waiver, or fabricated design artefact was
performed.

## Round 5 interrogation and capture

The round-4 non-analog residue was interrogated before changing code:

| Residue | Condition present? | Capability absent? | External? | Disposition |
|---|---|---|---|---|
| P0 `warn_acceptance_policy_check` | no; the design declares neither condition | no | no | Bucket-A applicability fix retained from round 4; absent declarations are typed N/A, not warnings |
| Step 4 behavioural evidence | no explicit behavioural-requirement list; only structural L9 arrays | no | no | Bucket-A extractor fix: ports/top-pins/clock domains are not behavioural requirements; explicit requirement lists still gate |
| Step 4 L10/coverage residue | L10 verification intents and a coverage measurement are present | yes for analog/oracle production; coverage is genuinely 11.11/0/0% | no | no capture of a false PASS; this is an upstream/design-evidence residue, not a parser defect |
| Step 9 PDK consistency | yes; generic Yosys netlist is present | no | no | Bucket-A escaped-identifier/type classification retained from round 4; generic-only is typed N/A, mapped mismatch still FAIL |
| Step 14 stage-analog producer | yes; analog stage is declared | no | no | Bucket-A pre-audit producer retained from round 4; the produced analog report still honestly FAILs A2-A4 |

The Step-4 extractor change is bidirectionally pinned: the pristine program
fails on structural-only L9 arrays (rc=1, reporting `clk`), while the captured
program returns `SKIPPED-CONDITION` (rc=2) for the same shape and still fails an
explicit behavioural requirement with no evidence. This is a general rule,
not a u_hawaii_adc literal.

Next: /vibe-ic-all after the local capture commit is reviewed and landed.

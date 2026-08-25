---
name: ppa-measure
description: Read PPA artefacts that the tools already wrote — STA reports, power reports, area reports, DEF/GDS summaries — and turn them into an evidence-linked measurement report of canonical `vibeic.ppa.metric.v1` records, each carrying its scope and its source hash. Use when the user says "measure PPA", "what is the real area/power/timing", "collect the PPA numbers", "post-route PPA", or when a report must state what was measured AND what was not.
---

# PPA Measure

## The boundary this skill lives inside

This skill produces an **evidence-linked report**. It never produces a
gate verdict, and no part of it asks the model to settle whether the design is
good enough. The pass/fail call belongs to a deterministic program —
`_ppa/feasibility.py` per `docs/PPA_INTERFACES.md` §4 — and this report only
supplies the records that program consumes.

Concretely, this skill may say *"setup WNS is -0.124 ns at the `ss` corner,
parsed from `<file>` whose sha256 is `<hash>`"*. It may not say what that number
means for the release. If a caller wants the release answer, the handoff is the
gate program, and the report says so on its own `Verdict authority:` line.

The reason for the split is not tidiness. A number that a model produced and a
number a parser produced look identical once they are in a table, and only one
of them can be re-derived from an artefact. Keeping the verdict in a program
keeps the re-derivable half load-bearing.

## When to use

Trigger when the user:
- Has finished a synthesis / PnR / STA / power run and wants the numbers collected
- Asks what the design's real post-route PPA is, as opposed to an early estimate
- Needs the inputs a feasibility gate or a Pareto comparison will read
- Needs an honest statement of PPA coverage — which metrics exist and which do not

**Not** this skill: an early, pre-synthesis guess. That is `ppa-predict`, and the
two must never be mixed in one table. A `ppa-predict` number carries status
`ESTIMATED`, which `docs/PPA_INTERFACES.md` §2 forbids from ever entering final
PPA; a `ppa-measure` number carries status `MEASURED` and a source hash.

## Inputs to gather

1. The design / run directory, and which stage it reached (synthesis, post-place,
   post-route, post-route-extracted)
2. The artefacts themselves: STA report(s), power report(s), area report, DEF or
   GDS summary — by path, one per view
3. The analysis views actually run: process corner, voltage, temperature, RC
   corner, clock, check type
4. The activity basis for any power number: vectorless, or a named VCD/SAIF
5. Whether an extracted-parasitics run exists, or only the pre-extraction estimate

If an input is absent, that absence is a result. Record it as `NOT_MEASURED`
with a `reason`; do not substitute a value from a different stage and do not
leave the row out.

## Workflow

1. **Enumerate the views before reading any number.** Write down the list of
   (stage, mode, process, voltage, temperature, rc_corner, clock, check) tuples
   the run was supposed to cover. This list is the denominator; without it a
   report of three green rows cannot be told apart from a run that only produced
   three rows.
2. **Parse, never recompute.** Each number is lifted from an artefact by a parser
   and hashed as parsed. A number you arrived at by arithmetic is `DERIVED` and
   must carry its formula alongside; a number you arrived at by judgement is not
   a measurement at all and does not belong in the table.
3. **Bind every record to its source.** `source.path`, `source.sha256`,
   `source.tool`, `source.parser`. A record without a resolvable source is
   `INVALID`, not `MEASURED`.
4. **Keep the taxonomy split.** Synthesis area and post-route area are different
   metrics, not two samples of one. Vectorless power and VCD power are different
   metrics. Pre-extraction and post-extraction timing are different metrics.
   Collapsing them is the single most common way a PPA table becomes a fiction.
5. **Emit the coverage line.** Count `MEASURED`, `NOT_MEASURED`,
   `NOT_APPLICABLE`. An unstated denominator is how "we measured everything"
   and "we measured what happened to be lying around" print the same page.
6. **Generate the report from the records — do not typeset it.** The markdown
   below is emitted by `programs/ppa_report_gen.py`, which reads the records and
   writes both the human page and the `claims.json` that binds every sentence in
   it to the artefact behind it. See the next section.
7. **Hand off.** Name the program that will read these records and state that the
   verdict is its output, not this document's.

## Where the records come from

Everything below consumes `vibeic.ppa.metric.v1` records, and until this section
existed nothing here said who WRITES them. Two producers do, and both need
`--json` — each writes its bundle only when handed one, so an invocation without
it runs and emits nothing:

```bash
# sign-off evidence: the physical, reliability and equivalence axes, read from
# a completed run's own artefacts (drc_signoff.json, lvs_verdict.json, antenna,
# IR, EM, equivalence) and emitted as canonical metric names
python3 plugins/vibe-ic/programs/ppa_signoff_records.py <project> \
    --json reports/ppa/records/signoff.json

# the design-for-ECO spare population, which the eco_readiness axis refuses from.
# It takes the two spare artefacts BY PATH, not a project root, and --preservation
# is optional precisely because step 34 writes it conditionally.
python3 plugins/vibe-ic/programs/ppa_eco_spare_records.py \
    --spare-plan phase3/stage3/pnr/spare_cells.json \
    --preservation reports/spare_preservation.json \
    --stage stage4 --json reports/ppa/records/eco_spares.json
```

`ppa_signoff_records` is the missing half of `ppa_feasibility_check`: that gate
proves its axes from canonical metric names, and before this producer existed
seven of those names were written by nothing in this tree — so a run that
measured DRC, LVS, antenna, IR, EM and equivalence still had no record saying
so. `ppa_eco_spare_records` exists because a place-and-route search once deleted
a design's entire spare-cell population and scored BETTER for it — smaller area,
lower power, and no axis anywhere saying the layout could no longer be repaired
by a metal-only ECO. The axis is the refusal; this program is the evidence it
refuses from.

THEY ARE RUN HERE AND NOT BY A FLOW CLAUSE, and the reason is recorded in the
flow yaml at step 37.5ic rather than guessed at. 37.5ic is the first step where
every axis they read coexists, which is why wiring them there was tried on
2026-08-25 — but one of the files they read, `reports/spare_preservation.json`,
is written by a CONDITIONAL clause at step 34 and is declared in no step's
`required_outputs`. A gate reading it therefore makes that path
produced-consumed-undeclared (d7 `W2`), and the repair reached for was an
UNCONDITIONAL `required_outputs` row over a conditionally-produced artefact —
which reds every spare-less design over a file nobody owes. What would make them
wireable is stated there too: a step that produces
`reports/spare_preservation.json` unconditionally and declares it. Until then
the honest runner is this line, and an operator who has a completed run in hand
has exactly the inputs the clause could not guarantee.

## The report is generated, and then it is checked

```bash
# records (file or directory of vibeic.ppa.metric.v1) -> page + claims
python3 plugins/vibe-ic/programs/ppa_report_gen.py <records.json|records_dir> \
    --out reports/ppa/report.md --claims reports/ppa/claims.json \
    --json reports/ppa/report_run.json

# the page may not say more than the claims support
python3 plugins/vibe-ic/programs/ppa_page_claim_check.py reports/ppa/report.md \
    --claims reports/ppa/claims.json --cite-numbers
```

**Why a generator and not a template.** A report is the last place a number is
touched before a human believes it, and a sentence carries implications an
artefact does not. `ppa_report_gen` is a gate, not a formatter:

| rc | meaning |
|---|---|
| 0 | the page and `claims.json` were written |
| 1 | `[REFUSE]` — a record cannot support the sentence it would become: a `NOT_MEASURED` carrying a `value`, a numeric sentinel (`0` / `-1` / `""`) standing in for "not measured", a collapsed single PPA score, or two records producing one claim id from different facts |
| 2 | `[CANNOT CHECK] NO_INPUT` (the path is not readable) or `EMPTY_CORPUS` (the path is there and holds no record — the zero is STATED, with the path it counted) |

An rc=1 is not a formatting problem to route around by writing the page by
hand. It is the generator naming a record you must fix upstream, in step 2 or
step 3.

**`claims.json` is the runnable half of the prose.** Every sentence a reader
will believe carries `[claim:<id>]`, and each claim names the artefact path and
hash that supports it. `ppa_page_claim_check --cite-numbers` then re-runs the
page every landing: a claim whose status outruns its weakest cited evidence, a
citation that resolves to nothing, and a sentence stating a number with no
citation are each rc=1. Prose cannot be re-read every landing; a citation can.

Pass the records path the way it should appear in the published page — the
generator quotes the path it was given, so a `/tmp/...` argument puts an
absolute machine-local path into the artefact and trips this skill's
`X_no_volatile_paths` cross-check.

The `NOT_MEASURED` rows are printed by the generator, with their `reason`,
never dropped. That is the same rule as step 5 and the "Do not" list below,
enforced once in a program instead of remembered three times.

## Do not

- Do not write `0`, `-1` or an empty string to mean "not measured". There are no
  numeric sentinels; there is a status field and it is `NOT_MEASURED` with a reason.
- Do not omit a row because it has no number. A missing row and a measured zero
  are different facts and a reader cannot tell them apart after the fact.
- Do not compare two numbers whose `scope` differs. That comparison is
  `UNDETERMINED`; it does not have a winner.
- Do not carry a `ppa-predict` estimate into this report, in any column, under
  any heading.
- Do not restate a program's exit code as your own conclusion. Quote it with its
  program name and its rc.
- Do not hand-write the report page when `ppa_report_gen` refuses your records.
  The refusal is about a record, and typing the page yourself publishes exactly
  the sentence the refusal was protecting a reader from.
- Do not report a number whose artefact you could not open. "I could not read it"
  and "I read it and it was empty" are different results and must print differently.

## Output format

The deliverable is one markdown report. The template below is the whole shape;
`<...>` are the parts you fill in.

    # PPA Measurement — <design> @ <stage>

    Verdict authority: _ppa/feasibility.py — this report states no pass/fail of its own.

    ## Summary
    <two or three sentences: which stage, which views were run, what is absent>

    Coverage: MEASURED=7 NOT_MEASURED=2 NOT_APPLICABLE=1

    ## Measurements

    | metric | status | value | unit | stage | corner | source sha256 |
    |---|---|---|---|---|---|---|
    | timing.setup.wns_ns | MEASURED | -0.124 | ns | post_route_extracted | ss/1.62V/125C | sha256:3f9a1c7d |
    | power.total_mw | NOT_MEASURED | - | - | post_route_extracted | - | - |

    ## Not measured, and why

    | metric | reason |
    |---|---|
    | power.total_mw | no activity basis: neither a vectorless run nor a VCD exists |

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | phase3/stage3/sta/sta_mcorner_ocv.rpt | sha256:b204e8a1 | opensta |

    Next: run /ppa-diagnose

Every row of `## Measurements` is the human view of one canonical record. The
records themselves are the machine deliverable and go in the report's JSON
sidecar, one per row, in the frozen shape:

```json
{
  "schema": "vibeic.ppa.metric.v1",
  "metric": "timing.setup.wns_ns",
  "status": "MEASURED",
  "value": -0.124,
  "unit": "ns",
  "scope": {"stage": "post_route_extracted", "mode": "functional",
            "process": "ss", "voltage_v": 1.62, "temperature_c": 125,
            "rc_corner": "max", "clock": "clk", "check": "setup"},
  "source": {"path": "phase3/stage3/sta/sta_mcorner_ocv.rpt",
             "sha256": "sha256:77c1de40", "tool": "opensta",
             "parser": "ppa_metric_extract.py"}
}
```

Serialize with `programs/_ppa/canonical_json.py` and nothing else — sorted keys,
no spaces, UTF-8, no NaN. A hash taken over a hand-rolled `json.dumps` is a hash
of a different document than the one the next reader will re-serialize.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-measure/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.
`compliance.yaml` in this skill directory enumerates every required element of
your output, and its `X_verdict_boundary` cross-check is what stops this report
from drifting into being a gate.

**Your task is not complete until the audit returns PASS.** Missing elements are
the single largest source of skill-execution non-determinism across agents.

# PPA interface freeze — v1

This document is the reason several authors can build different parts of the PPA
enhancement at the same time and have the pieces fit afterwards. It fixes the
things they would otherwise each decide differently: how a number is written
down, what an exit code means, which module owns which question, and who is
allowed to edit which file.

It is frozen. A change here is a change to everyone's work, so it lands as its
own commit that says what moved and why.

Source: `VIBE_IC_PPA_ENHANCEMENT_SPEC_v1.2_FINAL` §5, §6, §14, §15. Where this
document and the spec differ, the spec is right and this is a bug.

---

## 1. Exit codes — the contract every `ppa_*.py` honours

| rc | meaning |
|---:|---|
| `0` | PASS / VALID / ELIGIBLE |
| `1` | FAIL / REFUSED / INELIGIBLE — **a finding about the design** |
| `2` | UNDETERMINED / NOT CHECKED / REQUIRED EVIDENCE MISSING |
| `3` | INTERNAL ERROR / BAD INVOCATION — **never a design FAIL** |

**rc=1 is a claim about silicon. Do not use it to mean "I could not look."**
Measured 2026-08-21: two shipped gates refused with a bare `SystemExit("...")`,
which exits 1, and 1 in those files means "the STA engines disagree" and "a via
patch is narrower than its layer's minimum". A run that never opened an image
reported a hard finding. Use rc=2, and print a marker (`[CANNOT CHECK]` or
`[REFUSE]`) so a 2 can never be read as a silent skip.

**rc=2 must never be mapped to PASS by a flow gate.** A step that treats 2 as
green has a gate that cannot fail; v1.11.3 shipped exactly that and it took a
landing to notice.

Every CLI additionally: supports `--json <path>`; writes through
`_atomic_artefact`; puts the human summary on stdout and refusals on stderr;
and attaches a machine-readable code to every verdict.

## 2. The canonical metric record

One shape, `vibeic.ppa.metric.v1`. Numbers never travel alone.

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
             "sha256": "sha256:...", "tool": "opensta", "tool_commit": "...",
             "parser": "ppa_metric_extract.py", "parser_sha256": "sha256:..."}
}
```

| status | may enter a numeric comparison |
|---|---|
| `MEASURED` | yes |
| `NOT_MEASURED` | no — and it carries a `reason`, not a value |
| `NOT_APPLICABLE` | no — the contract must prove it does not apply |
| `INVALID` | no — the artefact exists but cannot support the metric |
| `ESTIMATED` | never in final PPA |
| `DERIVED` | per metric policy, and it carries its formula |

**No numeric sentinels.** `0`, `-1` and `""` never mean "not measured". A report
prints the literal `NOT_MEASURED` row; it does not omit it.

**A verdict is not a number.** A metric whose last name segment is `verdict`
carries a non-empty STRING value and declares `"unit": "verdict"`. Three of the
feasibility axes are proved this way: LVS answers whether two named circuits
match, equivalence answers whether a proof exists, and design-for-ECO tie-off
answers whether every spare input is tied — none of them is a
population, and encoding "matched" as the integer `0` puts a number where a
verdict belongs and invites arithmetic on it downstream. `_ppa/metrics.compare`
returns `NOT_NUMERIC` for a pair of verdicts and never a delta; whether a
verdict is acceptable is decided only by the feasibility axis that names the
literals it accepts.

**A `scope` key that is present and null is worse than one that is absent.**
`null == null`, so two records that could not read their corner compare as the
SAME corner. A field a producer could not establish is OMITTED and the reason is
recorded outside `scope`; the refusal that follows is the correct outcome.

**A record that may enter a numeric comparison must CARRY its unit.** Absent or
empty is refused (`NO_UNIT`); it is never inferred from the name. The name is a
cross-check on a declared unit, not a substitute for one.

**A metric NAME ending in a unit suffix is a claim about `unit`, and the two
must agree.** `timing.setup.wns_ns` carries `"ns"`, `area.die_um2` carries
`"um^2"`, and anything ending `_count` carries `"count"`. The unit names the
DIMENSION, never the thing counted: `area.proxy.cell_count` is `"count"`, not
`"cells"` — WHAT is counted is already stated by the metric name. The enforcer
is `unit_suffix_of` in `_ppa/metrics.py`, and it is the only cross-check in the
system positioned to catch an order-of-magnitude unit error, because every
consumer downstream trusts `unit`.

Measured 2026-08-21: `_ppa/area.py` declared `"cells"`, `"wires"` and
`"wire_bits"` for its three `_count` metrics while `_ppa/metrics.py` demanded
`"count"`. Two files in one lane holding opposite rules refused six records per
run. The registry moved, not the rule. Guard:
`tests/test_ppa_producer_consumer_agreement.py`.

**Two numbers are comparable only if their `scope` matches.** Synthesis area and
post-route area are different metrics. Vectorless power and VCD power are
different metrics. A comparison across differing scope is `UNDETERMINED`, not a
winner.

### 2.1 A SECOND record under one `(metric, scope)` identity

Three different things look alike here, and collapsing them is what made a
routine two-artefact run unreportable. `_ppa/metrics.MetricIndex.add` names
which one it found:

| what arrived | verdict | why |
|---|---|---|
| a byte-identical record | `DUPLICATE_RECORD`, refused | a set's size must not depend on how many times a producer ran |
| same `status`, `unit` and `value`; different `source` | **CORROBORATION**, accepted | two artefacts state one fact. The record is kept once and `corroborations` in the bundle names every artefact that stated it |
| different `status`, `unit` or `value`, from different bytes | `CONFLICTING_RECORD`, refused | two artefacts state DIFFERENT facts under one identity; a claim citing it binds to neither |
| different value from the SAME bytes | `SAME_ARTEFACT_TWO_VALUES`, refused | identical bytes cannot support two numbers — a parser defect, not a fact about the run |

**Agreement is not a conflict.** Measured 2026-08-21 on a real run tree:
`route.drc.violation.count` read `0` from `openroad.log` and `0` from
`openroad.metrics.json`, and the index refused the pair as "two numbers claiming
to be the same fact" when the two numbers were EQUAL. One corroborated fact took
down the whole record set and no report could be generated from a default run.

**"Same artefact" is decided by `source.sha256`, never by `source.path`.** The
runner publishes each STA report into two directories, so two paths routinely
name one artefact and every timing row was emitted — and refused — twice.

**A parser never settles a conflict and neither does an index.** The backend
emits BOTH readings with different `source.path`
(`_ppa/backends/__init__.py`), the index DETECTS the disagreement, and settling
it is a declared authority decision in `_ppa/contract.py`
(`policy.resolvable_fact_keys`, opt-in and named). Moving the artefact into
`scope` to make the collision go away is NOT a fix: it converts a detected
conflict into two facts that quietly never compare again.

**If two readings really are one reading, the SCOPE is wrong — fix that.** A
metric emitted once per reported path under one scope
(`timing.*.worst_path_slack_ns`, three values, one view) is not a conflict and
not corroboration; the scope is missing the field that tells the readings apart.

### 2.2 Required views are declared PER AXIS

`_ppa/feasibility.FeasibilityPolicy` reads `required_views` (global) and
`required_views_by_axis` (per axis, falling back to the global list for any axis
it does not name). The two exist because the axes are not measured in one
scope namespace: setup and hold sign off across process corners, while DRC, LVS,
antenna, IR, EM, equivalence and design-for-ECO readiness are single
measurements over one database and have no process corner at all. With one global list, a contract declaring its
timing corners also demanded them of DRC, so either DRC was permanently
uncovered or its producer had to emit one measurement N times under fabricated
scopes — N records carrying one source hash, into an index whose job is to
notice exactly that.

**What this does not change:** an unmeasured required view still makes the axis
UNDETERMINED. A corner nobody ran is a corner nobody ran. There is no spelling
that means "whatever was measured is enough" — an axis named with an empty list
is UNDETERMINED, exactly as an undeclared global list is.

**Every axis result publishes its `coverage`**: one row per declared view saying
`MEASURED`, `NOT_MEASURED` (a record covers the view and could not support the
metric — with the reason and the artefact it came from) or `NO_RECORD` (nothing
covers the view). Those two used to be one sentence, and they need different
fixes: one needs a better artefact, the other needs a run. The coverage is
published on a SATISFIED axis too, so a reader questioning whether the view set
was the right one does not have to make the axis fail first.

## 3. Identity

`_ppa/canonical_json.py` is the only serializer. `digest_of(obj)` produces the
`sha256:<hex>` that goes into a document. Never hand-roll `json.dumps` for
anything whose hash is taken — sorted keys, no spaces, UTF-8, no NaN.

Hash the value you PARSED, never one you recomputed. A number you computed is
`DERIVED` and states its formula.

### 3.1 The five identities, and what belongs in each

| identity | what it holds | may it differ between two arms? |
|---|---|---|
| `problem` | the design, the constraints, the PDK, the target corners | **no** — whichever arm won, won a different contest |
| `implementation` | the RTL / netlist / the candidate's own source, **and every artefact produced from it** | **yes** — this is the one axis an experiment may move |
| `analysis` | how the measurement was TAKEN: corners, extraction, activity basis, the measurement scripts | **no** — differ here and the numbers are not the same metric |
| `toolchain` | the image and tool builds | **no** — the difference may be the tools rather than the design |
| `agent_execution` | what an agent was permitted to do, and under which policy | recorded, not compared |

**AN ARTEFACT THAT VARIES WITH THE IMPLEMENTATION MAY NOT SIT IN `analysis`.**
`analysis` is the measurement CONFIGURATION — the inputs to taking a reading.
It is never the reading. An STA, DRC, LVS or power REPORT is an OUTPUT of the
implementation and belongs in `implementation`.

This rule was implicit until v1.11.33, and its most natural reading made the
system useless. "Analysis artefacts" reads like "the artefacts the analysis
produced", so an author declares the sign-off reports there — and then
`ppa_problem_integrity_check` refuses **every** legitimate comparison with
`PPA-C-012: the analysis identity DIFFERS`. Of course it differs: those files
are outputs, and the two arms have different implementations by construction.
Measured on a real 61-arm run, moving the reports to `implementation` and
leaving `analysis` holding the measurement configuration only takes the same
check from `rc=1` to `rc=0` with no other change.

`PPA-C-016` now names this case: when `analysis` differs **and**
`implementation` differs, the artefacts that moved are named as misfiled, with
the rule, instead of the reader being handed a bare digest mismatch.

**A hash-based identity over an EMITTED script is defeated by the run
directory.** A generated analysis script that embeds absolute host paths hashes
differently on every run, so two runs of an identical measurement configuration
refuse. Either emit it with paths relative to the project root, or leave it out
of the identity **and say so** — never drop it silently.

## 4. Module map — one question per module

```
_ppa/canonical_json.py   serialization + sha256                       [FROZEN, done]
_ppa/identity.py         problem / implementation / analysis / toolchain / agent identity
_ppa/provenance.py       artefact hashes, run manifest, evidence manifest
_ppa/contract.py         build, validate, authority order, conflict detection
_ppa/metrics.py          the record above: construct, validate, index, coverage
_ppa/timing.py           per-view timing rows from STA artefacts
_ppa/power.py            power split + activity basis provenance
_ppa/area.py             area taxonomy: proxy vs physical, kept separate
_ppa/feasibility.py      the hard gate: setup/hold/DRV/DRC/LVS/ANT/IR/EM/
                         equivalence/eco_readiness. The last is the one axis
                         whose APPLICABILITY the design declares: a design that
                         declares no spare/ECO requirement gets NOT_APPLICABLE
                         from it, and a design that declares one cannot be
                         promoted without meeting it. See `AXIS_NOT_APPLICABLE`
                         and `FeasibilityPolicy.eco_requirement`.
ppa_eco_spare_records.py the design-for-ECO spare population as canonical
                         records, from the flow's own spare_cells.json (the
                         producer side of the axis above)
_ppa/signoff.py          the physical/reliability/equivalence axes, read out of
                         the flow's own sign-off artefacts (the producer side of
                         the gate above)
_ppa/pareto.py           frontier over the triple; never over a collapsed scalar
_ppa/closure.py          controller state machine: actuator, remeasure, rollback, stop
_ppa/search.py           candidate lifecycle, budget, multi-fidelity
_ppa/benchmark.py        arms, fairness conditions, independent scorer
_ppa/agent_context.py    read-only evidence context, hash-bound
_ppa/agent_router.py     Program-First diagnosis; explicit handoff only
_ppa/agent_policy.py     allow-list, autonomy level, blast radius, budget
_ppa/casebook.py         evidence-signed cases + design fingerprint compatibility
_ppa/distillation.py     case lifecycle RAW -> ... -> PROGRAMMED
_ppa/backends/exec.py    ONE container invocation: command, mounts, cwd,
                         cpu-seconds, tool version, invocation provenance
_ppa/backends/{opensta,openroad,yosys,librelane,orfs}.py   tool-specific parsing only
```

A backend module parses one tool's output into canonical records and does
nothing else. No thresholds, no verdicts, no policy — those live in the domain
module, so that adding a tool never changes a rule.

RUNNING the tool is the other half of that sentence, and `_ppa/backends/exec.py`
owns it. Until this line existed the map named a parser and named no caller, so
every function that starts a container had nowhere to go. Measured on
`programs/phase3_one_shot_runner.py` (41,136 lines, 8,745 of them PPA): **6,111
PPA lines — 70% — anchor on eleven invocation helpers** (`_docker_exec`,
`_docker_exec_raw`, `_container_mounts`, `_to_container_path`,
`_container_cpu_seconds`, `_tool_version`, `_tool_from_command`,
`_split_shell_chain`, `_log_invocation`, `_hash_declared_outputs`,
`_tool_status_not_the_log_sinks`) and cannot be extracted into a module this
document never named. A silent map is not a neutral map; it is a map that says
"leave it in the runner" without anyone having decided that.

`exec.py` runs ONE invocation and records what it was: the command, the mounts,
the working directory, the cpu-seconds it consumed, the tool version behind it,
and the provenance of the call. It obeys the same rule as the parsers — no
thresholds, no verdicts, no policy — so "which tool ran" and "is the result
acceptable" stay two questions in two modules.

This is an OWNERSHIP line, not a schedule. Moving the eleven helpers is a large
extraction with its own A/B and it belongs to whoever does it; what changes here
is that the destination now exists to move them to.

## 5. Schema conventions

Files live in `schemas/ppa/<name>.v1.schema.json`. Every instance document
carries `"schema": "vibeic.ppa.<name>.v1"` as its first key. A schema is
versioned by filename; `v1` is never edited once something has hashed against
it — a change is `v2`.

Each domain author writes the schema for their own domain. `contract.v1` belongs
to the contract lane.

## 6. File ownership — how twelve authors avoid each other

Each lane owns its files exclusively. If you need a change in someone else's
file, write it in your RESULT.md and it is applied at landing; do not edit it.

**Three files have a single writer and it is the lander:**

| file | why |
|---|---|
| `flow/phase1_phase2_phase3.yaml` | collided four times in one night |
| `programs/INDEX.md`, `PROGRAM_INVENTORY.json`, the README counters | generated; both sides of a conflict are wrong and the merged tree is neither |
| `tools/ci/protected_landing_transition.json` | a hash list rendered against one base; a text merge produces a manifest that matches no tree |

Need a flow step, a gate clause, or a protected-path move? State it in RESULT.md
as a request. It gets applied in one batch, in one commit.

## 7. What "done" means for every lane

Four fixtures, no exceptions:

| fixture | proves |
|---|---|
| positive | green when it should be green |
| negative | **red** when it should be red |
| vacuous | missing input gives rc=2 with a marker — not rc=0, not rc=1 |
| mutation | revert the change and a named test goes red |

The vacuous one is not paperwork. A gate whose declared invocation exits 2 on
absent input can never fail, and this repository has shipped that twice.

And the honest-measurement rule that costs the most when it is skipped: **"the
run finished with no failures" and "the run never started" both print zero.**
Check the summary line, not the failure count.

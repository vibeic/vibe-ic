# HANDOFF — programmable NVM must have a way in for its programming supply

**Branch**: `fix/nvmpinpath-programming-supply-terminal`
**Worktree**: `/home/reyerchu/vibe-ic-wt-nvmpinpath`
**Base**: `28313227` (v1.5.86) — see *Base drift* below, this is **not** 1.5.85
**Version**: unassigned — the gatekeeper assigns it at land
**Not pushed.** Local commit only.

---

## The convention being fixed into the plugin

Any **programmable non-volatile memory** — one-time-programmable, fuse-based,
multiple-time-programmable, antifuse; the whole family — is **written** at a
voltage **above the digital core supply**, delivered **from outside the die**
through a **dedicated terminal**: a package pin for in-field programming, or a
wafer-probe pad for programming before the part ships. **Reading** it generally
needs only the core supply.

That asymmetry is the trap. A read-only integration looks complete. A design
that intends to *program* and has no programming terminal passes every digital
check while being unable to do the one thing it was built for.

Corroboration, stated generically: within a single process, two **independent**
programmable-memory IP families — one native to the process, one third-party —
both specify their programming supply as **externally supplied**, and both
specify a voltage window **above that process's core supply**. Two unrelated
vendors do not converge by accident; they converge because the cell cannot be
written at core voltage. This is physics, not a selection preference.

### The inference chain

1. A design instantiates such a memory **and** its RTL carries programming
   control logic (program request / address / data / busy) ⇒ it **intends to
   program** the part at some stage.
2. Programming intent **requires** a physical path for the programming supply:
   a package pin, or a probe pad. There is no third option — the supply cannot
   be manufactured on-die from the core rail.
3. Neither present ⇒ the design **cannot do what it says it does**, and nothing
   in the digital flow notices. What surfaces is five steps later and names
   none of this: synthesis tie-cells the macro's supply pin, a signal net lands
   on a power terminal, and detailed routing aborts.

---

## What changed

### 1. Expert layer — so it gets asked in Phase 1

| File | Change |
|---|---|
| `agents/qbank/any-ic_L1.yaml` | 4 new question groups: `nvm_programming.{present,technology,programming_stage,program_supply_pin}`, tiered expert/intermediate/beginner with `follow_ups` |
| `agents/class_kb/templates/any-ic.yaml` | new **optional** typed L1 fact `nvm_programming` (the destination those answers land in) |
| `agents/ic_expert_db/ic_expert_db.json` | new `ic_class: fuse-programmable-nvm-integration`, 2 craft lessons |

**Why `qbank/any-ic_L1.yaml`.** This *is* the Phase-1 dialogue mechanism — the
question bank the IC-expert reads, keyed by fact path, tiered by the user's
expertise, with `follow_ups` that map an answer onto a default. It is the only
place in the tree where "IC-expert proactively asks X in Phase 1" is a real,
executed behaviour rather than prose someone might read.

**Why the root class `any-ic`, not a memory class.** A processor, a crypto
engine, a protocol IC and a sensor front-end can all embed a fuse array for
trim, keys, calibration or a serial number. This is not a property of the
design's class — it is a property of the memory. Putting it in
`memory-controller.yaml` would miss every design that actually hits it.

**Why `class_kb/templates/any-ic.yaml` as well, and not instead.** qbank asks
against fact *paths*; a question whose answer has no typed destination is not
asked twice. That is exactly the #309 failure mode — the information existed in
a descriptive layer and never reached the layer the back end consumes, so a
completeness model scored it as captured while the back end built a supply
network without it. The slot is `required: false`, so no existing design becomes
non-conformant, and `present: false` is a complete honest answer.

**Why NOT `agents/lessons/ic_expert_L1.md`.** That file is a rigid
benchmark-derived schema with an explicit *"Forbidden: do NOT add extra
top-level keys … The extractor expects this exact schema."* Adding a field
there would violate the file's own contract and break the extractor.

*Note on the DB header counters*: the base file stored `"classes": 99` against
**100** actual entries — a pre-existing off-by-one that no gate catches
(`ic_expert_db_consistency_check` recomputes the count and never compares it to
the stored field). My edit sets it to the true `101`, so the diff reads `99 →
101` rather than `100 → 101`. `total_lessons` was already correct (160 → 162).
Flagging it rather than burying it, since it is a change I did not set out to
make.

**Reachability was measured, not assumed** (`ic_expert_db_query`):

| prompt | rank of the new lesson |
|---|---|
| sensor front-end with an on-die eFuse array for trim values | **2** |
| crypto engine with antifuse key storage burned after packaging | **2** |
| microcontroller with OTP memory storing a serial number | **5** (inside the production `k=5` digest, but only just — `serial-*` classes outrank it because `serial` is a strong function-noun stem, ×12.0 in the ranker) |
| a simple UART peripheral with a baud-rate divider | absent (correct) |

### 2. Program layer — extended, not new

| File | Change |
|---|---|
| `programs/hardmacro_supply_intent.py` | **extended**: `lef_all_pins`, `NVM_TECHNOLOGY_TOKENS` / `PROGRAM_ACTION_TOKENS`, `identifier_tokens`, `program_intent_evidence`, `nvm_technology_evidence`, `external_entry_for`, `assess_program_supply` |
| `programs/nvm_program_supply_pin_check.py` | **new** gate (I/O + orchestration + reporting only) |
| `programs/phase3_one_shot_runner.py` | inline blocking pre-flight at the top of `main()` |
| `flow/phase1_phase2_phase3.yaml` | gate wired at Step 14 (last pre-PnR step) |
| `programs/tests/test_nvm_program_supply_pin_check.py` | 25 tests |
| `programs/INDEX.md` | regenerated |

**Why extend `hardmacro_supply_intent.py` rather than write a second module.**
Its own docstring is emphatic: *"two copies of this judgement would drift, and a
drifting supply rule is how the pin got lost in the first place."* The
judgement belongs there. `lef_pg_pins` is now a filter over the new
`lef_all_pins` — one LEF grammar, not two — and the existing #309 tests pass
unchanged, which is the proof that refactor was behaviour-preserving.

**Why a separate gate program nonetheless.** The new question needs project
I/O the existing decision module deliberately does not do (RTL parse, top-level
port resolution, pad-declaration lookup), and it needs to be a *flow gate* with
its own exit code so it can be wired and enforced. Judgement stays in the shared
module; the gate is plumbing.

### The two questions are genuinely different

| | #309 (already landed, v1.5.86) | this |
|---|---|---|
| asks | is this supply pin **declared** in the power-intent layer? | is there a **physical external entry** for it? |
| blocks | the symptom: signal net on a power terminal aborting routing | the cause: the design was never given a way in |
| when | inside `step_pnr`, before routing | top of `main()`, before any step |

**A design can pass #309 and fail this one.** #309 is satisfied when L21
declares the rail — but L21 describes *internal* rails, and an internal rail can
never answer for a supply that is above core voltage by definition. That gap is
the thing this closes.

---

## Enforcement: this gate **BLOCKS**. Measured, not inferred.

The repo's own audit says 62 of 72 gates cannot stop the step they guard, so
the claim is stated explicitly and then demonstrated by running.

**1. The shipped `flow_gate_enforcement_audit`, before vs after:**

```
v1.5.86 baseline          with this change
  gates      : 72           gates      : 73
  ENFORCED   : 10           ENFORCED   : 11   <-- this gate
  AUDIT_ONLY : 62           AUDIT_ONLY : 62   (unchanged)
  declared   : 1            declared   : 2    <-- ENFORCEMENT: blocking
  contradictions: gds_substance_check (pre-existing, unchanged)
```

No gate moved from ENFORCED to AUDIT_ONLY; no new contradiction; no new orphan.
A test asserts this by *calling the audit*, so the claim and the measurement
cannot drift.

**2. Actually run, not reasoned about** — `phase3_one_shot_runner` on the
broken fixture:

```
runner exit                 = 5      (refused)
blocking message emitted    = yes
backend artefacts produced  = 0      (no netlist, no DEF, no GDS)
refusal report written      = reports/phase3/nvm_program_supply_pin.json
```

and the **same runner on the fixed fixture** gets past the pre-flight (it then
exits 1 on an unrelated container-mount preflight — *not* 5, and zero NVM
findings).

---

## Verification

**Negative control, both directions.** The two fixtures differ by exactly one
top-level port:

| | CLI exit | verdict |
|---|---|---|
| before the fix (no programming pin) | **1** | `NVM_PROGRAM_SUPPLY_PIN_ABSENT` |
| after the fix (`inout wire VPGM`) | **0** | PASS |

Both directions are also exercised end-to-end through the phase-3 runner
(above) and under both rail-naming conventions.

**Corpus sweep — 77 designs × 3 rail configurations = 231 runs, 0 false
positives.** Corpus: `benchmark-data/ic/*` plus every `campaign_v1*/`,
`campaign_*/`, `sha256_stage2_run`, `spm_cleanup_backup_*` on this host.
76 of 77 skip cleanly (no hard macro). The one design that has a real macro
(a volatile RAM: one `USE POWER` pin) evaluates and **passes** — the single
POWER pin is the core rail the PDN provides, so nothing is required from
outside.

**Full test suite**: see *Suite result* at the bottom.

---

## chip-AGNOSTIC / NDA boundary

No macro name, pin name, vendor, PDK, SKU or voltage number appears in any
shipped file. Everything is read from the design's own inputs:

* **which pin is a supply** — the macro's own LEF `USE POWER` record;
* **which supply is the core rail** — the design's own declared rails (L21, or
  the staged standard-cell LEF's `USE POWER` pin names, or `--rail`);
* **which names reach the outside** — the design's own top-level port list plus
  its own declared pinout/pads.

The **only** literals are two generic English/EDA vocabularies, kept
**deliberately separate**:

* `NVM_TECHNOLOGY_TOKENS` = `otp mtp nvm efuse antifuse fuse` — what the part
  **is**. Context for the report; **never** sufficient to raise anything.
* `PROGRAM_ACTION_TOKENS` = `program prog pgm burn blow` (+ inflections) — the
  **act** of writing a fuse cell. Only these establish programming intent.

Folding them into one vocabulary would raise a *blocking* finding on a
perfectly correct design: a macro named `otp_*`, instantiated read-only,
programmed by its IP vendor before delivery, legitimately has no programming
terminal. Naming the memory family is not a plan to write it. There is a test
for exactly that design.

`write`/`we`/`wr`/`wdata` are excluded from both — an SRAM write is not a fuse
programming operation, and including them would fire on every design with a RAM
macro (tested). These words classify intent; they never identify a part. Same
generic vocabulary `otp_image_layer_consistency_check` already relies on.

**Known limit, stated rather than hidden**: a design whose programming signals
carry *no* action verb at all (e.g. only `otp_req` / `otp_busy`) reads as
no-intent and is recorded, not raised. Since this gate BLOCKS, under-firing
with an explicit disclosure is the right way to be wrong.

`source_chip_agnostic_check`: **PASS**. A test asserts none of the fixtures'
own pin names appear in the gate source.

All test fixtures are synthetic and neutral (`fuse_array_256x8`, `ram_1024x32`,
`romblock_256x8`, pins `VDD`/`VPGM`/`VSS`). §4.05 respected: the gate reads
`rtl/`, `input/pdk_local/`, `input/pdk/`, `phase1/generated_docs/` — design
input only, never an oracle or golden artefact.

---

## Honesty boundaries — where this gate deliberately does NOT fire

* **No programming intent** ⇒ recorded as `NVM_NO_PROGRAM_INTENT` (INFO,
  exit 0), never raised. A part programmed by its IP vendor before delivery
  carries no programming logic, needs no programming terminal, and is a
  legitimate design. Silence would be dishonest; raising would be a false alarm.
  The note names the detected technology, and says plainly that naming the
  family is not a plan to write it.
* **Rail names that don't line up** (the design says `VPWR`, the macro says
  `VDD` — routine). We can no longer say *which* pin is the core supply, only
  that **at most one** is. The verdict stays correct in both directions but the
  message says exactly that much and no more, rather than fabricating a
  diagnosis. `core_rail_identified` in the JSON records which case applied.
* **A single `USE POWER` pin** is always treated as the core rail. Never fires.
* **SKIP (exit 0) with an explicit reason** when: no macro LEF; no staged macro
  is instantiated; no parsable RTL; or the top module is ambiguous (0 or >1
  instantiation-graph roots). An unknowable port list must skip, not guess.
* A **probe pad declared in the design's own pinout/pad list** counts as an
  external entry even when it is not an RTL port — otherwise the gate would
  force every factory-programmed part to invent a port it does not need.
* **Existence, not connectivity.** The supply pin is matched to a top-level
  port / declared pad **by name** — the same discriminator `_rail_token_match`
  already uses for #309, and the only one available, since a hard macro's
  supply pins are physical-only and normally absent from its Verilog stub
  entirely (there is no RTL net to trace). A design that *declares* the port
  and then fails to route it to the macro is **not** caught here — that is the
  PDN's and #309's territory, and a later, different defect. What is caught is
  the earlier and more total one: the terminal does not exist at all, so no
  downstream work can connect it. Stated in the gate's own docstring too.

---

## Two things the gatekeeper should know

### 1. Base drift — this is on v1.5.86, not 1.5.85

The task specified plugin cache **1.5.85** as "origin/main latest". I verified
that (cache `1.5.85/programs/phase3_one_shot_runner.py` was byte-identical to
`origin/main@790b257c`). **During this session `origin/main` advanced to
`28313227` (v1.5.86) — "#309: block BEFORE routing when a hard-macro PG pin has
no rail".**

That matters directly: **`programs/hardmacro_supply_intent.py` did not exist at
v1.5.85.** It is *new in v1.5.86*. The module I was told to read, understand and
not duplicate only landed mid-session. This branch is therefore based on
`28313227`, and the baseline test run was re-done against `28313227` after the
drift was noticed (the first baseline, started against v1.5.85, was discarded).
**The 1.5.85 cache is stale for this area** and should not be used to review
this change.

### 2. A concurrent writer was active in the first worktree

My original worktree `/home/reyerchu/vibe-ic-wt-progsupply` was **not private**.
Another process, committing as `reyerchu <charlieway60@gmail.com>`, rebased my
branch onto `28313227`, committed my in-progress edits as a WIP commit
(`d3a0f52e`), and dropped two of its own draft files
(`nvm_program_supply_intent.py`, `nvm_program_supply_check.py` — a different
design for the same problem) into my tree. A sibling worktree
`/home/reyerchu/vibe-ic-wt-progsupply-core` on branch
`fix/progsupply-core-expert-parse-track` also exists.

I relocated to `/home/reyerchu/vibe-ic-wt-nvmpinpath` on a fresh branch and
transplanted **only** the files I authored. **Those two draft files are not in
this branch** and I make no claim about them. If a second agent was dispatched
on this task, its output needs separate review — the two approaches should not
be merged blind.

---

## Adjacent defect found, NOT fixed (deliberately out of scope)

`flow_gate_enforcement_audit._GATE_RE` only recognises the plain
`program_exit_zero: "<gate> …"` form. Gates written in the
`optional_program_exit_zero:` → `command:` / `condition_files_exist:` sub-key
form collapse to a single pseudo-gate named `command` and are **invisible to
the audit entirely** — including both `yosys_*` gates at Step 14. So the
published "72 gates, 62 audit-only" figure is measured over an incomplete
population.

I did not fix it: widening the regex would change #306's just-published
headline numbers and would surface a new set of contradictions, which the
audit's own docstring says is *"an owner's call, not a side effect of an audit
tool."* I worked around it by wiring this gate in the plain form (documented
inline in the flow YAML) so its enforcement claim is verifiable by the shipped
audit. **Recommend filing this separately.**

---

## Files changed

```
 agents/class_kb/templates/any-ic.yaml            |  +36
 agents/ic_expert_db/ic_expert_db.json            |  +10 -2
 agents/qbank/any-ic_L1.yaml                      |  +74
 flow/phase1_phase2_phase3.yaml                   |  +20
 programs/INDEX.md                                |   +6 -4   (regenerated)
 programs/hardmacro_supply_intent.py              | +286 -9
 programs/nvm_program_supply_pin_check.py         |  new
 programs/phase3_one_shot_runner.py               |  +43
 programs/tests/test_nvm_program_supply_pin_check.py | new (25 tests)
```

Gates run clean: `source_chip_agnostic_check` PASS ·
`ic_expert_db_consistency_check` PASS (101 classes / 162 lessons) ·
`ic_expert_db_health_audit` no new warnings ·
`test_programs_index_freshness` PASS · `flow_gate_enforcement_audit` exit 0.

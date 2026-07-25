# HANDOFF — #312 second track, and its first payload (#313 programmable-NVM programming supply)

**Worktree** `/home/reyerchu/vibe-ic-wt-progsupply-core` (task code `progsupply`)
**Branch** `fix/progsupply-core-expert-parse-track`
**Base** `origin/main` @ `82eff7f2` (v1.5.87)
**Pushed** no. Local commit only, as instructed.
**Version** NOT stamped. The gatekeeper assigns it at land; three files need the
bump (`.claude-plugin/marketplace.json`, `vibe-ic-marketplace/.claude-plugin/marketplace.json`,
`vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json`), all currently 1.5.87.

---

## READ FIRST — a concurrent agent worked the same issue

While I was working, another agent was writing into
`/home/reyerchu/vibe-ic-wt-progsupply` (branch `fix/progsupply-nvm-program-supply-pin`),
on the same defect, in the same minutes. Files it changed there between 20:34
and 20:39: a new `nvm_program_supply_pin_check.py` and its test, a rewritten
`hardmacro_supply_intent.py` (211 lines → 23 KB), plus `ic_expert_db.json`,
`any-ic.yaml`, `qbank/any-ic_L1.yaml` and `flow/phase1_phase2_phase3.yaml`.

That tree was pre-existing when I started and I initially worked in it. On
finding the contention I moved to a private worktree cut fresh from
`origin/main` and re-verified everything there. **Nothing in this handoff was
built or measured in the contended tree.**

That agent also landed `v1.5.87` on main while I worked. **My work builds on it
and deliberately changes two of its tests** — see "Tests I inverted on purpose"
below. There is likely a second, overlapping branch for this same defect that
you will need to adjudicate against this one. I have not looked at its content
beyond noticing the filenames.

---

## What was actually wrong

The doctrine is program-first + AI-backup **dual-track convergence**. Phase 1
had one track.

v1.5.87 (#312) established and named that: `ai_deep_review_patches.json` has
three readers and zero writers, no Phase-1 program invokes the IC Expert to
parse anything, and `ic_expert_backup_pack` — the module built for exactly this
hand-off, carrying a measured A/B (38→31 folded, 51 as independent authors) —
is referenced by nothing but INDEX.md and its own test. Its commit message ends:

> NOT done: wiring the second track.

This branch wires it, and gives it a real first payload.

---

## Was `ic_expert_backup_pack` the original mechanism?

**Yes — but for a different question, and only on the benchmark driver.**

Its docstring states the doctrine verbatim (Track 1 skills-digest author,
Track 2 DB-informed author, converge by diffing). But both its tracks are **AI
authors**, its `output_target` is `rtl.sv`, and its convergence is a body-vs-body
diff. Its only callers are `benchmark/cvdp_task_loop.py` and
`benchmark/cvdp_phase1_entry.py` — the CVDP **RTL-authoring** path. There is no
L-doc anywhere in it.

So it is the doctrine's own assembler, instantiated for spec→RTL and never
connected to Phase-1 parsing.

**Decision: reuse it, do not fork it.** The assembly step (retrieve, render the
two *independent* digests, write the contract, emit the descriptor) is
target-agnostic and already tested. The only change is one keyword argument:

```python
def assemble(..., output_target: str = "rtl.sv")
```

Default unchanged, so the RTL hand-off is byte-identical for its original
caller (pinned by a test). The Phase-1 parse track passes
`output_target="l_doc_expectations.json"`. What was genuinely missing — an
L-doc **expectation set** and an item-by-item comparison — is a different
concern and lives in its own program, per this repo's one-decision-module +
one-gate convention.

---

## The three things that landed

### 1. `phase1_expert_parse_track.py` — the second track (ADVISORY findings, MANDATORY execution)

Reads the design input **independently**, derives what the L-docs *should*
contain from expert knowledge, then compares item by item and names every
divergence individually. Not a count: the finding id is
`EXPERT_TRACK_EXPECTATION_UNMET::<rule>::<layer-target>::<macro>/<pin>`, and
each finding carries the input evidence it rests on plus the **verbatim expert
DB lesson** it comes from.

The expectation SET is derived from input only (macro LEF + input RTL). The
L-docs are read solely to decide `met`. That split is what makes it a second
track rather than a second reading of the first track's output.

Two sub-tracks:
- **deterministic** — always runs, no LLM. Calls the *same* decision module the
  blocking gate calls, so the two evaluations of one convention cannot drift.
- **AI** — handed to `vibe-ic:ic-expert-agent` via `ic_expert_backup_pack`.

**Degrading without going silent** (the explicit requirement):
- no LLM backend → `SKIPPED-CONDITION`, emitted as its own **named finding**
  (`EXPERT_TRACK_AI_SUBTRACK_SKIPPED`), printed by the runner and recorded in
  the report, with the text "read them as a floor, not as coverage".
- the track itself fails → **exit 1, Phase 1 fails**. The report is a mandatory
  output; the runner deletes any prior report first, so "the report exists" can
  only mean *this* run wrote it. Timeout and any rc outside {0,2} are failures.
- nothing applies → exit 2 (`VACUOUS_PASS`) with a stated per-rule reason.

So the *findings* are advisory — a divergence needs a human to converge — while
*running* is not optional. That asymmetry is the whole point.

### 2. The convention, in the expert layer

`agents/ic_expert_db/ic_expert_db.json`, new entry `ic_class: "nvm-fuse-array"`.
13-line diff; the file's exact serialisation (`indent=1`, no trailing newline)
was verified by round-tripping before the edit, so there is no reformat noise.
Passes `ic_expert_db_consistency_check` (blindness, oracle-source ban, advisory
boundary, related-link integrity): `PASS (classes=101 lessons=161)`.

**Why there and not the other two candidates:**
- `agents/lessons/ic_expert_L*.md` are **L-doc JSON schema** lessons ("the
  top-level keys must be exactly these"). Wrong shape entirely.
- `agents/class_kb/templates/*.yaml` are **per-ic_class required fact paths**.
  "Has a programmable NVM" is a *feature*, not a class; putting it in `any-ic`
  would make it required for every design and produce fleet-wide false
  positives.
- `ic_expert_db.entries[]` is chip-agnostic design-class craft, retrieved by
  `ic_expert_db_query`, defined as ADVISORY. The DB's own `_consistency` rule
  ("lessons are advice; they do NOT assert hard rules a gate checks") is
  satisfied precisely because the hard rule lives in the deterministic gate and
  the lesson only states what an expert should ask for.

**Class-name choice worth knowing:** `ic_expert_db_query._fn()` scores a class
name 12.0 per matched function-stem, and `"ram"` is a substring of `"program"`.
Any name containing `program` (or `ram`) would have scored 12 against every
prompt containing the word "program" and hijacked the top-k for unrelated
designs — against the measured finding that widening the author's context lowers
recovery. `nvm-fuse-array` matches no stem. Retrieval is not load-bearing here
anyway: the rule resolves the entry by exact `ic_class`, so a finding's
justification never depends on how the design's prose happened to score.

### 3. `nvm_program_supply_intent.py` + `nvm_program_supply_check.py` — the deterministic track (BLOCKING)

`ENFORCEMENT: blocking`. Fires only on the full combination:

1. a macro whose own LEF declares **≥2 distinct `USE POWER` pins**, AND
2. the design's **input RTL instantiates** it, AND
3. that RTL carries **programming-control logic**, AND
4. **no terminal** at the design's own boundary corresponds to one of those
   supplies, and no gap is declared.

**No name literal anywhere.** Condition 1 *is* the convention expressed
structurally: a memory that must be burned needs a read supply and a
programming supply, so it declares two supply terminals. A single-supply macro
declares one and never reaches the module — which is what keeps every ordinary
SRAM instance out without an exclusion list. Pin↔terminal matching reuses
#309's `_rail_token_match` (whole-token, does not split on the underscore).

The one place a vocabulary is unavoidable is condition 3 — "programming-control
logic" cannot be recognised without knowing what the operation is called. It is
a **closed, documented set of generic operation words** (the same shape as the
existing `_CORNER_TOKENS` and `_REGMACRO_SUFFIXES` in this repo), matched on
**whole name tokens** so `progress` never matches `prog`. It contains no part
number, process name, SKU or IP model. A PROGRAM-category token alone is not
enough: at least one of address / data / handshake must also be present,
because a burn is not a single-cycle write. That is what keeps a **read-only**
user of a programmable macro out of the finding set.

**Boundary sources** (union — a supply present in any of them is credited):
input RTL ports, `L1.pinout` / `pin_table`, `L5.pads`, `L9.top_level_ports`,
`L7` probe/test pads, `L21` supply pins.

**Escape hatch:** #309's field, unchanged —
`L21.fields.hard_macro_supplies[{master, pin, integration_gap: true}]`. Sharing
the field means a design that discloses once is disclosed to both gates.
`integration_gap` must be explicitly `true`; merely naming the pin buys nothing
(pinned by a test).

**A third verdict, and why it does not block.** When *not one* of the macro's
supply or ground pins appears in the boundary inventory, the inventory records
no supply terminals at all and cannot answer the question. Blocking there would
flag every design whose pinout has not been extracted yet — a different defect
with a different owner. That case is `INCONCLUSIVE`, rc 0, with its own named
and printed finding `NVM_PROGRAM_SUPPLY_BOUNDARY_NOT_STATED`. Reported, not
swallowed. **If you would rather this blocked too, it is a one-line change** —
I judged it the wrong trade, but it is your call.

### Why it blocks in Phase 1 rather than deferring like #309 does

#309 warns in Phase 1 and blocks in Phase 3 because there *is* a later
observation: the routing abort. Here there is none. The digital logic is
entirely well-formed — it simulates, lints, synthesises, times, routes, and
passes DRC and LVS. The first observation is at bring-up, on silicon, on an
array that will not take a burn. There is nothing to defer to, so deferring
means never catching it. Given #306 measured that 62 of 72 gates can only
describe a run afterwards, a 63rd would have been pointless.

### Relationship to #309, precisely

#309 asks: *is this macro PG pin claimed by a rail the design declares?*
This asks the earlier question: *granted a rail is declared — is there a PIN
that brings it in from outside?* A rail declared in the power-intent layer with
no terminal at the boundary is a supply that exists only on paper. I read #309
first and reuse its LEF grammar, its rail matcher and its escape hatch rather
than restating any of them; #309 landed with a bug in exactly that matcher, and
a second drifting copy is how that bug comes back.

---

## Wiring, and why there

Both are invoked from **`phase1_one_shot_runner.py`**, not from the 57,705-line
`phase1_doc_one_shot_runner.py`:

- it is the one entry point covering **both** input modes, and both emit
  L-docs. Wiring only the docs backend would leave every dialogue-entered
  design unexamined.
- `flow_gate_enforcement_audit._RUNNERS` inspects `phase1_one_shot_runner.py`
  and **not** the docs backend. A gate wired where the audit cannot see it
  reads as `AUDIT_ONLY`.

Both are also registered in `flow/phase1_phase2_phase3.yaml` step 0 (converted
to `gate: all_of:`, the shape step 2 already uses).

**Measured, by running the audit:**

```
{'gate': 'nvm_program_supply_check',  'enforcement': 'ENFORCED', 'declared': 'blocking'}
{'gate': 'phase1_expert_parse_track', 'enforcement': 'ENFORCED', 'declared': 'advisory'}
```

The audit still exits 1 overall, on the pre-existing `gds_substance_check`
contradiction. **Confirmed pre-existing** by running the same audit on an
untouched v1.5.87 worktree — same rc, same single contradiction. Not mine.

---

## Integration with v1.5.87 — tests I inverted on purpose

v1.5.87's `phase1_expert_track_evidence_check` decides RAN/NEVER_RAN from the
**sidecar**, and detects wiring by looking for a *direct* import of the hand-off
module in a Phase-1 runner. Both assumptions break the moment the track is
actually wired, and would make that gate quietly lie. Two changes:

1. `expert_track_wired()` now accepts **one** level of indirection — a runner
   that names the track program, which itself imports the hand-off module.
   Both ends must be real: a runner naming a track program that never reaches
   the hand-off is still *not wired* (tested), same lesson as its bare-mention
   guard, one level down.
2. `assess()` reads the **track's own report first**, falling back to the
   sidecar. Necessary because the track deliberately does not write the sidecar
   (next section) — reading only the sidecar would report `NEVER_RAN` for a
   track that demonstrably ran.

Findings carry `about: "design" | "track"`. The evidence check counts only
`design` findings for RAN vs RAN_EMPTY, so a run whose *only* entry is "my AI
half was unavailable" reads as **ran, found nothing** — not as a track that
found something. That is #312's own two-zeros rule applied one level in.

Two of its tests were written to fail on exactly this progress and say so in
their own docstrings ("when the expert track is finally wired, this test fails
and must be updated deliberately"). Both are **inverted, not deleted**, so they
stay non-vacuous in the other direction — removing the wiring now fails them:

- `test_312_the_repo_today_really_is_never_ran` → `test_312_the_track_is_now_wired`
- `test_312_handoff_module_exists_but_is_orphaned` → `test_312_handoff_module_is_no_longer_orphaned`

---

## Deliberately NOT done: writing the AI-patch sidecar

The missing writer for `phase1/ai_deep_review_patches.json` is what exposed the
missing track, so writing it looks like the obvious close. **It would be a
cheat.** All three gates that read that file **merge its contents into the very
haystack they then measure for completeness**. A track writing its own
expectations there would score itself: tokens it supplied come back as
"captured", and coverage rises by exactly the amount the track invented. That
is the failure mode #309 named `rail_undeclared` — manufacturing 100% coverage
against rails that exist only inside one's own mapping.

The track records `track_health.ai_patch_sidecar_present` so the gap stays a
**visible fact** rather than an inference, and a test asserts the track never
writes it. Closing it properly needs a patch source independent of the gate
doing the measuring — a real task, and a separate one.

---

## Verification — every claim below was produced by running it

### Enforcement, proven by real runner runs (not by reading code)

| run | result |
|---|---|
| defect present → `phase1_one_shot_runner` | **rc 1** — blocked, `NVM_PROGRAM_SUPPLY_NO_EXTERNAL_PATH` naming `mem_array_512x32/VPROG` |
| terminal added → same runner | **rc 0** — *while the expert track still reports 3 findings*. Findings present, run not blocked |
| track program removed → same runner | **rc 1**, `"the Phase-1 expert track cannot run and its absence must not pass silently"` |

The middle row is the actual proof that the two severities differ: same runner,
same session, findings on screen, exit 0.

### Gate verdict paths, each exercised

rc 1 defect · rc 0 after adding the terminal · rc 0 via declared
`integration_gap` · rc 2 `VACUOUS_PASS` on a single-supply design · rc 0
`INCONCLUSIVE` with a named finding when no boundary is stated.

### Negative control, both directions

Bidirectional at the module, gate and track level: FAIL before the fix, PASS
after, for each of the three. Plus the inverse controls — a read-only user of a
programmable macro, a macro stub that is not an instantiation, a lone PROGRAM
token with no supporting signals, `progress` not matching `prog`, a second
ground not counting as a second supply, and a `hard_macro_supplies` entry
without `integration_gap: true`.

### Corpus sweep — zero false positives

All 9 fleet designs under `benchmark-data/ic/`, through the gate and through
the track:

```
caravel_user_project  edge_llm_accel  edge_llm_matmul_accel  ibex  opentitan_aes
sha256  spm  subservient  u_hawaii_adc
      nvm gate rc=2 (VACUOUS_PASS) · expert track rc=2, 0 unmet expectations
```

`edge_llm_accel` is the one design carrying a real memory macro, and it skips
for exactly the intended structural reason: that macro declares a single
`USE POWER`. Sweep artifacts were removed from the corpus afterwards; the tree
is clean.

### Full test suite

Both runs are against separate worktrees, compared on the **set of failing test
names**, not counts. Numbers are filled in at the bottom of this file.

---

## Known limits, stated plainly

- **The AI sub-track has never actually executed.** This host has no
  `anthropic` SDK and no API key, so `SKIPPED-CONDITION` is the real path for
  every run above. Its other two branches (`HANDOFF_EMITTED`, `CONSUMED`) are
  exercised deterministically in tests — `assemble()` makes no network call —
  but **no LLM has read a pack and returned expectations.** The convergence
  half of dual-track convergence is wired and untried.
- **Only one deterministic expectation rule exists.** `DETERMINISTIC_RULES` is
  a one-tuple. The track is a mechanism with one payload, not a body of
  knowledge.
- **The rule stands down when no boundary is stated.** If a design records no
  supply terminals at all, the expert track emits no expectations for it
  (the deterministic assessment returns not-applicable) and the gate reports
  `INCONCLUSIVE` instead. Conservative on purpose; the reason is recorded in
  the report, but it does mean a design with no pinout gets less scrutiny from
  this rule, not more.
- **`ic_expert_db.classes` is still 99 against 101 entries.** Pre-existing
  drift, not enforced on the shipped DB (the assertion that binds them runs on
  a temp DB). I updated `total_lessons` because my entry changes it, and left
  `classes` alone rather than bury an unrelated correction in this diff.
- **Not claimed:** no live containerised flow run, no silicon, no measurement
  on a design that actually contains a programmable NVM macro. Every fixture is
  synthesised. The convention itself is general and independently corroborated;
  the *fixtures* prove the mechanism, not the physics.

## NDA

No chip codename, PDK name, SKU, vendor part number or memory IP model appears
in any code, comment, test, fixture, file name, variable name or commit message
on this branch. The corroboration is stated in generic form only: two unrelated
programmable-memory IP families on one process, one process-native and one
third-party, specifying the programming supply identically. A test asserts the
shipped lesson contains no part-number shape, no process-node shape, and no
die-dimension shape.

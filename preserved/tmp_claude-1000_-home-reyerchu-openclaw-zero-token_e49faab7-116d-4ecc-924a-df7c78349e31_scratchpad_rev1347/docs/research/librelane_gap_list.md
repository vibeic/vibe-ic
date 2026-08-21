# LibreLane → Vibe-IC gap list

Scope: what LibreLane CHECKS that Vibe-IC does not, and what therefore reaches
silicon through us. Not a survey of what LibreLane is — that is already published
and was re-measured, not re-derived (see §0).

## §0 Provenance, and the 16-vs-101 reconciliation

Read from the canonical repository, cloned to this host:

    https://github.com/librelane/librelane
    git clone --depth 1   ->   head bf8cc13c3b6314a099fabac208393d323cc5bfe2
    committed 2026-08-17 14:56:06 +0300, "hotfix: fix bash syntax in ci"
    pyproject.toml: version = "3.0.10"   (the clone carries no tags: `git describe` fails)

Every measurement below was taken by putting THAT clone first on `sys.path`
inside the EDA image and asserting `librelane.__file__.startswith("/clone")`, so
the numbers are the repository's, not the image wheel's.

**Caution about the image wheel.** `ghcr.io/vibeic/vibeic-eda:0.2.29` ships
`librelane-3.1.0.dev1`, and despite the higher version string it is NOT this
tree: `steps/klayout.py` differs by 86 lines, and the difference runs the wrong
way — the clone at 3.0.10 has `KLAYOUT_DRC_DEFINES` with a deprecation shim for
`KLAYOUT_DRC_OPTIONS`, while the 3.1.0.dev1 wheel still has the old name. The
image's librelane is off the main line. Nine of the ten files this report cites
are nevertheless byte-identical between the two
(`steps/step.py`, `steps/checker.py`, `steps/magic.py`, `state/state.py`,
`state/design_format.py`, `common/types.py`, `scripts/odbpy/disconnected_pins.py`,
`flows/classic.py`); the tenth, `steps/klayout.py`, differs only in that rename,
and the XOR step this report cites is identical at lines 340-354.

### The reconciliation

`librelane/steps/` holds **16 entries** — module FILES. The published **101** is
registered Step CLASSES. Both are correct; they count different things, and the
mechanism is explicit.

**Registration mechanism.** A Step class is registered by the decorator
`@Step.factory.register()` (`librelane/steps/step.py:1461-1474`), which stores
the class under `cls.id.lower()` in the factory's private dict and refuses any
class whose `.id` is still `NotImplemented`. Because the key is the id, the
registry cannot hold duplicates, so `Step.factory.list()`
(`steps/step.py:1485-1490`) returns one entry per registered class.
`Flow` uses the identical pattern (`@Flow.factory.register()`).
`DesignFormat` does NOT: it registers an *instance* via
`DesignFormat(...).register()` (`state/design_format.py:92-93`), and the factory
also indexes every `alts` entry (`state/design_format.py:120-130`), while
`list()` returns `.id` per registry VALUE (`state/design_format.py:142-147`) —
so its raw `list()` is 46 for 23 formats.

**Counts at bf8cc13, by two independent instruments.**

| quantity            | static (source) | runtime (clone's own registry) | published | verdict   |
|---------------------|-----------------|--------------------------------|-----------|-----------|
| registered Steps    | 101 `@Step.factory.register()` sites | 101 | 101 | CONFIRMED |
| Flows               | 8 `@Flow.factory.register()` sites   | 8   | 8   | CONFIRMED |
| DesignFormat views  | 23 `.register()` call sites          | 23 unique ids (46 registry entries) | 23 | CONFIRMED |
| files in `steps/`   | 16              | —                              | not published | — |

The 101 decorator sites live in 10 of the 16 files
(openroad.py 33, odb.py 21, checker.py 21, klayout.py 10, magic.py 7,
pyosys.py 4, misc.py 2, yosys.py 1, verilator.py 1, netgen.py 1). The other six
are infrastructure and register nothing: `__init__.py`, `__main__.py`,
`step.py`, `tclstep.py`, `common_variables.py`, `openroad_alerts.py`.
The 23 DesignFormat sites: 17 in `state/design_format.py`, plus 2 in
`steps/magic.py`, 2 in `steps/openroad.py`, 1 in `steps/klayout.py`,
1 in `steps/pyosys.py`.

**Verdict on our published page: NO DRIFT. 101 / 23 / 8 are all still true at
bf8cc13.** The only correction is to the instrument, not the number: anyone
re-measuring the DesignFormat row must use
`len(set(DesignFormat.factory.list()))` AFTER `import librelane.steps`. The raw
call returns 46 (alts double-count) or 34/17 (before the steps modules import
and register the remaining formats). A count taken any other way is a
measurement of the import order.

## §1 The five gaps, ranked by silicon consequence

### GAP 1 — Magic's own extraction error channel is unread  [class: DEAD CHIP, with a clean signoff report]

**WHAT THEY CHECK**
`steps/magic.py:642` — after `scripts/magic/extract_spice.tcl` runs,
`illegal_overlap_count = count_occurences(f, "Illegal overlap")` over the
step's `feedback.txt`; re-counted from parsed bounding boxes at
`steps/magic.py:659-666`; classified at `common/drc.py:263-268`
(`vio_rulenum = "ILLEGAL_OVERLAP"`). Published as metric
`magic__illegal_overlap__count`, consumed by `Checker.IllegalOverlap`
(`steps/checker.py:216-234`, threshold 0, measured), which the default flow runs
between `Magic.SpiceExtraction` and `Checker.LVS`
(`flows/classic.py:111-114`).

**WHAT WE CHECK**
Nothing. Searched the whole plugin for `illegal.{0,3}overlap` — 0 files.
Searched `feedback\.txt|extract_spice|magic.*feedback` — three hits:
`programs/magic_extract_spice_emit.py`, `skills/analog-extraction-resim/SKILL.md`,
`programs/INDEX.md`. `magic_extract_spice_emit.py` validates that the emitted
TCL *contains* `extract all` and `ext2spice lvs` — the commands, never their
complaints. Searched the LVS side — `programs/lvs_report_check.py`,
`lvs_tapeout_signoff_check.py`, `lvs_verdict_tokens.py`,
`lvs_power_aware_extract_tcl.py` — all read netgen's verdict, none reads
magic's extraction feedback.

**THE GAP**
Magic can fail to resolve a layer overlap into a legal device, emit the SPICE
netlist anyway, and record the complaint only in `feedback.txt`. Vibe-IC's LVS
verdict is then computed from an extraction the extractor itself flagged, and no
artefact in the run records that it did. Whether netgen independently catches
any particular illegal overlap is NOT DETERMINED — I did not run a case. What IS
determined: the signal exists, upstream gates it at zero, and nothing in vibe-ic
reads it. The shippable artefact is a GDS carrying an LVS PASS whose input was
uncorroborated.

**OWNER** — a new `programs/magic_extraction_feedback_check.py`. Does not exist.
It must be BLOCKING and must sit BEFORE the LVS verdict gate, not after.

### GAP 2 — no cross-writer GDS agreement check on ordinary designs  [class: DEAD CHIP]

**WHAT THEY CHECK**
`flows/classic.py:100-106` streams the same routed database out twice —
`Magic.StreamOut` and `KLayout.StreamOut` — keeps them as two distinct views
(`mag_gds`, `klayout_gds`, `state/design_format.py`), then runs `KLayout.XOR`
(`steps/klayout.py:340-345`, docstring: "if there's any difference between the
GDSII streams between the two tools, one of them have it wrong") and
`Checker.XOR` (`steps/checker.py:289-306`, metric
`design__xor_difference__count`, threshold 0, measured). Needs no golden.

**WHAT WE CHECK**
`programs/xor_layout_check.py` — but its XOR is assembled-GDS vs a GOLDEN
REFERENCE for a Caravel / Open-MPW submission, with a blackbox-macro allow-list.
`programs/signoff_ladder_run.py:951-965` and
`programs/caravel_wrapper_harden_driver.py` only feed that same golden XOR.
Searched for `mag_gds|klayout_gds` across the plugin — 0 non-test files. The
flow emits one artefact, `phase3/stage4/gds/*.gds`
(`flow/phase1_phase2_phase3.yaml:4655-4724`), and
`provenance_check --tool=klayout,magic,openroad` records WHICH tool wrote it,
not whether two writers agree.

**THE GAP**
Every vibe-ic design that is not a Caravel submission holding a golden GDS gets
zero geometric cross-check. This is precisely the defect class a single-writer
DRC cannot see: DRC runs on the same stream that is wrong, and reports clean.

**OWNER** — `programs/xor_layout_check.py` should grow a second, golden-free
mode (writer-vs-writer), or a sibling program should own it. The Caravel mode
must not be the only mode.

### GAP 3 — signal terminals owning no net are invisible to both our instruments  [class: DEAD CHIP; but their instrument is defective, see §3]

**WHAT THEY CHECK**
`scripts/odbpy/disconnected_pins.py` walks the routed odb and classifies every
instance iterm and every top-level bterm by polarity and signal type, counting
those with no owning net (`Port.connected`, lines 40-128). Metric
`design__critical_disconnected_pin__count`, consumed by
`Checker.DisconnectedPins` (`steps/checker.py:235-252`) — threshold 0 and
`deferred = False`, i.e. a HARD stop, run in the default flow at
`flows/classic.py:92`.

**WHAT WE CHECK**
Two instruments, and neither covers signal terminals:
* `programs/phase3_one_shot_runner.py:5266` emits `PG_NET_OWNERSHIP_AUDIT` — an
  odb walk with exactly the right predicate (`[$iterm getNet] eq "NULL"`) and an
  unusually honest scope comment — but restricted to POWER/GROUND by
  `if {$_pg_s ne "POWER" && $_pg_s ne "GROUND"} { continue }`.
* `programs/erc_float_owner_classify.py` classifies OpenROAD
  `report_floating_nets` output. That reports NETS with no driver; a terminal
  that owns no net at all is not a net and cannot appear there.
Searched `getITerms|getNet\] eq "NULL"|getSigType` across `programs/` — hits only
in `phase3_one_shot_runner.py` and `macro_obs_geometry_intersect_check.py`.

**THE GAP**
A signal iterm, or a top-level port, with no owning net passes both. Macro pins,
blackboxes, DFT and spare-cell wiring are where this happens.

**OWNER** — extend the existing `PG_NET_OWNERSHIP_AUDIT` emitter in
`phase3_one_shot_runner.py` to SIGNAL, reported as a separate counter. Do NOT
port upstream's aggregation: it is broken (§3(b), §3(c)).

### GAP 4 — `assign` in the gate-level netlist is only caught when the netlist has NO cells  [class: WORKS BUT FAILS A CORNER / SHIPS LATE]

**WHAT THEY CHECK**
`Checker.NetlistAssignStatements` (`steps/checker.py:28-65`): opens the netlist
file, `^\s*\bassign\b` per line, reports file:line for each, then
`raise StepError` — a hard, non-deferred stop, `ERROR_ON_NL_ASSIGN_STATEMENTS`
default True. Runs right after synthesis (`flows/classic.py:49`). Notable: this
is one of the few upstream checks that reads its own evidence off disk rather
than a metric, so §3(a) does not apply to it.

**WHAT WE CHECK**
`programs/synth_netlist_check.py` flags `assign` only inside
`if total_cells == 0:` (lines ~313-345) — a yosys expression-form detector whose
fingerprint is "≥1 always AND ≥1 assign AND zero `$_*_`". A netlist with real
cell instances plus a handful of assign aliases never enters that branch.
`programs/rtl_hygiene_lint.py` operates on RTL, not the gate netlist. Searched
for any program failing on assign in the gate netlist — none.

**THE GAP**
Assign-aliased nets reach PnR. They alias net names, which is what breaks SPEF
back-annotation, antenna attribution and LVS name matching downstream — each of
which then reports a defect that is not where it appears to be.

**OWNER** — `programs/synth_netlist_check.py`. It exists; the predicate must be
lifted out of the `total_cells == 0` branch.

### GAP 5 — the PDK revision a run signed off against is never recorded  [class: SHIPS LATE / NOT REPRODUCIBLE]

**WHAT THEY CHECK**
`librelane/pdk_hashes.yaml` pins a PDK commit per open-PDK family — three
families, two distinct commit SHAs, one shared between two of them;
`common/misc.py:78-92` `get_pdk_hash()`; `flows/cli.py:520`
`opdks_rev = volare_pdk_override or get_pdk_hash(pdk)` then hands it to ciel to
enable exactly that revision. LibreLane version ↔ PDK commit is a declared pair.
Honest limit: with `--manual-pdk` there is no hash check at all — it is an
install-time pin, not a verification of an already-installed tree.

**WHAT WE CHECK**
Searched `pdk_hash|pdk_commit|pdk_rev|opdks_rev|volare|ciel` — 12 non-test
files, none binding a commit. `programs/input_doc_pdk_claim_vs_installed_pdk_check.py`
decides a document's claims against the installed PDK;
`programs/pdk_registry_selectable_check.py` checks selectability;
`programs/provenance_hash_audit.py` hashes gate OUTPUTS, not the PDK. Our pin is
the container image, which is a real pin — but runs that mount a local tree
(`--pdk-map`, `shared_pdk`, `/pdk`) carry no recorded revision at all.

**THE GAP**
Two runs of the same design can be signed off against two different DRC decks or
Liberty sets, with nothing in the artefacts distinguishing them. This is the
question a foundry asks after the fact, and today we cannot answer it for a
mounted PDK.

**OWNER** — `programs/provenance_hash_audit.py` should extend to the PDK tree
(or a sibling should), recording a revision/digest per run.

## §2 Answers to the four questions the brief posed

1. **Declared outputs.** Ours must refuse; **theirs does not.** LibreLane refuses
   a missing required INPUT (`steps/step.py:1158-1163`, `StepException`) but
   never checks that a step produced its declared OUTPUTS. `views_updates` is
   merged as overrides onto `state_in` (`steps/step.py:1181-1183`), so a step
   that declares an output and produces nothing leaves the PREVIOUS step's file
   in that slot and the next step's input check passes on it. Measured (§3(e)).
2. **Config resolution.** No provenance is recorded. `config/variable.py`'s
   `Variable` has no field naming the layer that supplied a value; the resolved
   `Config` is a flat immutable dict, and the `config.json` each step writes
   carries only `meta = {librelane_version, step}` (`steps/step.py:1146-1154`).
   A value that fell back to a default is indistinguishable from a design that
   set the same value. Its own docstring notes a PDK setting a non-PDK variable
   is "silently ignored". We are not clearly better here — adopt nothing, import
   nothing.
3. **Checkers between steps passing on an empty input set.** Yes — all of them.
   Measured, §3(a).
4. **The state/metrics object.** `State` threads views plus an immutable
   `metrics` dict; every checker asserts on a metric NAME, never on the artefact.
   We assert on artefacts (`files_exist`, `provenance_hash_audit` sha256+mtime),
   which is why §3(a) is not a defect class we share.

## §3 Upstream checks that CANNOT FAIL — evidence

All measured at bf8cc13, running the clone's own code (`librelane.__file__`
asserted to start with `/clone`), inside the EDA image for its dependencies.

(a) **All 20 registered `MetricChecker` steps PASS on an empty metrics dict.**
    `steps/checker.py:112-133`: `metric_value = state_in.metrics.get(...)`; when
    it is `None` the step warns ("Are you sure the relevant step was run?") and
    returns `({}, {})` — success. Ran each of the 20 on `State({})`: 20 PASSED,
    0 raised. The list includes `Checker.LVS`, `Checker.MagicDRC`,
    `Checker.KLayoutDRC`, `Checker.KLayoutAntenna`, `Checker.XOR`,
    `Checker.SetupViolations`, `Checker.HoldViolations`.
    Positive control (so the instrument is known to be able to fail): the same
    five checkers with a violating metric each raised `DeferredStepError`.
    A crashed or skipped producer step is therefore indistinguishable from a
    clean result at the checker.
(b) **`instance_critical_disconnected_pin_count` returns 0 for a cell whose ONLY
    pins are power and ground and BOTH are unconnected.**
    `scripts/odbpy/disconnected_pins.py:114-128` is an `elif` chain; for an
    instance with `outputs == 0` the second arm (`outputs_connected == 0`) is
    True, adds 0, and short-circuits the power/ground arms. Measured:
    `disconnected_pin_count = 2`, `instance_critical_disconnected_pin_count = 0`.
    That covers tap, decap, fill, endcap and diode cells — exactly the cells for
    which an unconnected supply is a latch-up / well-bias defect.
(c) **`top_module_critical_disconnected_pin_count` returns 0 when 63 of 64 top
    inputs are disconnected.** Same file, lines 98-111: "at least one of each
    kind needs to be connected". Measured: `disconnected_pin_count = 63`,
    `top_module_critical_disconnected_pin_count = 0`. `Checker.DisconnectedPins`
    reads only the critical number, and is `deferred = False` — a hard gate that
    fires only in the all-or-nothing case.
(d) **`State.validate()` passes on paths that do not exist**, despite the
    docstring "Ensures that all paths exist in a State" (`state/state.py:228-253`).
    Its visitor checks the key is a known DesignFormat and the value is a
    Path/dict/list — it never calls `Path.exists()`, which does exist
    (`common/types.py:57-68`) and is not called here. Measured: a State holding
    two nonexistent paths validated clean.
(e) **A step that declares an output and produces none returns normally, and
    forwards its predecessor's file.** Registered a `LazyStep` with
    `outputs = [nl]` whose `run()` returns `({}, {})`, started it on a state whose
    `nl` was an earlier file. `start()` returned normally; `state_out["nl"]` was
    still the earlier file, contents intact.
(f) **A required input whose file was deleted from disk is accepted.** The
    input check (`steps/step.py:1158-1163`) tests `value is None` — key presence,
    not file existence. Measured: state entry pointing at a removed file, step
    ran.
(g) **`Checker.WireLength` has a `None` default threshold** and is skipped with a
    warning (`steps/checker.py:105-108`). Measured across all 20: the other 19
    default to 0, so this is the only instance of that path.

## §4 What upstream is WORSE at — adopt selectively

* **Do NOT adopt the MetricChecker shape.** Asserting on a metric NAME means an
  absent producer reads as a clean result (§3(a)). Our §4.05 stance — absent
  evidence is INCOMPLETE, never a fabricated PASS, as in
  `programs/xor_layout_check.py` — is the correct one and must not be traded away
  when we adopt the CONTENT of their checks.
* **Do NOT adopt their declared-output contract.** Ours refuses; theirs does not
  (§2.1). Our `required_outputs` (61 of 63 steps declare it) plus
  `programs/step_required_inputs_check.py`, which exits 2 when a declared input
  is not among the naming step's declared outputs, is strictly stronger.
* **Do NOT adopt `State.validate()`.** It never touches the filesystem (§3(d)).
  `programs/provenance_hash_audit.py` compares sha256 AND mtime-against-gate-run,
  which is the check its docstring describes.
* **Config provenance: neither side has it.** Nothing to adopt; noted so it is
  not mistaken for a place to copy from.

## §5 The typed Step contract, at bf8cc13 — how it is declared, how far it is enforced

This is the piece we intend to adopt: a declared output that is absent becoming a
refusal BY CONSTRUCTION, instead of something each gate re-checks for itself.
Read it before adopting it — the declaration is worth taking, the enforcement is
half-built.

### How the declaration is written

`librelane/steps/step.py:453-458` — three class variables, two of them sentinel:

    id: str = NotImplemented
    inputs: ClassVar[List[DesignFormat]] = NotImplemented
    outputs: ClassVar[List[DesignFormat]] = NotImplemented
    config_vars: ClassVar[List[Variable]] = []

Documented at `step.py:404-416`: `inputs` are "required for this step. These will
be validated by the `start` method"; `outputs` are those that "may be emitted",
and "a step is not allowed to modify design formats not declared in `outputs`".
Note the asymmetry in the prose itself — inputs are *validated*, outputs *may* be
emitted.

Declaration is MANDATORY and enforced at class level: `step.py:610-615` refuses
to instantiate or use any subclass that left `id`, `inputs` or `outputs` at
`NotImplemented` — "Abstract step … does not implement the .{attr} property and
cannot be {action}". A composite step derives both from its constituents
(`step.py:1514-1537`). This part is sound, and it is the part to copy: a step
CANNOT exist without saying what it reads and what it writes.

`DesignFormat` also carries per-format optionality — `mkOptional()`
(`state/design_format.py:152-153`) sets `_instance_optional`, which the input
check honours — so "required" vs "optional" is a property of the declaration,
not of the checking code.

### How far it is enforced

**Inputs: enforced, at key level.** `step.py:1158-1163`, inside `start()`, before
`run()` is called:

    for input in self.inputs:
        value = state_in_result.get_by_df(input)
        if value is None and not input.optional:
            raise StepException(f"{type(self).__name__}: missing required input '{input.id}'")

Measured, positive control: a step declaring `inputs=[nl]` started on `State({})`
raises `StepException: E2: missing required input 'nl'`. The instrument can fail.

But the predicate is `value is None` — key presence, not file existence.
Measured: a state entry pointing at a file that was **deleted from disk** is
accepted and the step runs.

**Outputs: not enforced at all.** After `run()` returns, `step.py:1177-1183`:

    metrics = GenericImmutableDict(state_in_result.metrics, overrides=metrics_updates)
    self.state_out = state_in_result.__class__(state_in_result, overrides=views_updates, metrics=metrics)

`views_updates` is merged as OVERRIDES onto the incoming state. Nothing compares
`views_updates.keys()` against `self.outputs`. The only post-run check is
`self.state_out.validate()` (`step.py:1185-1190`), and that never touches the
filesystem (§3(d)).

Three consequences, each measured at bf8cc13:

| case | result |
|---|---|
| Step declares `outputs=[nl]`, `run()` returns `({}, {})` | `start()` returns success; `state_out["nl"]` is still **the previous step's file**, contents intact |
| Step declares `outputs=[nl]`, returns `{"nl": Path("/does/not/exist.nl.v")}` | `start()` returns success; `state_out["nl"]` is a path that does not exist |
| Next step declares `inputs=[nl]` and consumes either of the above | passes its input check — the key is present |

So on a missing output the answer to "refusal, or a downstream step reading a
stale file?" is: **a downstream step reading a stale file**, silently, with the
stale artefact also written into `state_out.json` as if this step had produced
it. On a *present but nonexistent* output it is worse: the state records a path
no tool ever wrote, and the refusal is deferred until whichever downstream tool
first tries to open it — attributing the failure to that tool, not to the step
that lied.

### What to adopt, and what to add

Adopt: the mandatory, class-level, machine-refused declaration. That is the part
that removes per-gate re-checking, and it is exactly what our
`required_inputs` / `required_outputs` already express in
`flow/phase1_phase2_phase3.yaml` (56 of 63 steps declare inputs, 61 of 63 declare
outputs) and what `programs/step_required_inputs_check.py` already
cross-validates.

Do NOT adopt the enforcement, because there is none to adopt. Whatever we build
must close all three of these, which upstream leaves open:

1. after a step returns, assert that every non-optional declared output is
   present in the step's own updates — not merely present in the merged state,
   which is how a stale predecessor artefact satisfies it;
2. assert the declared path EXISTS on disk, and is non-empty — the input check
   and `State.validate()` both stop at key presence;
3. bind the artefact to THIS run — a path that exists because a previous run
   wrote it is the same failure as a stale state entry. Our
   `programs/provenance_hash_audit.py` already compares sha256 and
   mtime-against-gate-run; that is the predicate the contract needs, applied at
   the step boundary rather than at audit time.

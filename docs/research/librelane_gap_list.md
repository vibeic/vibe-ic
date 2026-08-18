# LibreLane → Vibe-IC gap list

Scope: what LibreLane CHECKS that Vibe-IC does not, and what therefore reaches
silicon through us. Not a survey of what LibreLane is — that is already published
and was re-measured, not re-derived (see §0).

## §0 Provenance and the delta against the published survey

Read from the copy shipped in the pinned EDA image, not from the web:

    image   ghcr.io/vibeic/vibeic-eda:0.2.29 (image id 45fd4d622fe1)
    path    /usr/local/lib/python3.12/dist-packages/librelane
    version librelane.__version__ == "3.1.0.dev1"
            (dist-info METADATA: Name librelane, Version 3.1.0.dev1)

The published survey was read at tag 3.0.8. The copy available here is
3.1.0.dev1, a pre-release of the next minor. NOT DETERMINED: I did not reach a
git checkout of tag 3.0.8, so per-commit diffing was not possible; only the
published counts could be re-measured.

Re-measured, at 3.1.0.dev1:

| published claim        | measured now | verdict     |
|------------------------|--------------|-------------|
| 101 registered Steps   | 101          | CONFIRMED   |
| 8 Flows                | 8            | CONFIRMED   |
| 23 DesignFormat views  | 23           | CONFIRMED   |

Flows measured: Chip, Classic, OpenInKLayout, OpenInMagic, OpenInOpenROAD,
Optimizing, SynthesisExploration, VHDLClassic.

No drift to correct. One instrument note for whoever re-measures the third row:
`DesignFormat.factory.list()` returns 46, not 23, because `alts` are registered
as extra keys and `list()` returns `.id` per registry *value*
(`state/design_format.py:121-147`). It returns 34/17 if called before
`import librelane.steps`, because the step modules register the remaining
formats on import. The correct instrument is
`len(set(DesignFormat.factory.list()))` AFTER importing `librelane.steps`.
A count taken any other way is a measurement of the import order.

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
`librelane/pdk_hashes.yaml` pins a PDK commit per family
(sky130 `d815bb30…`, gf180mcu `d815bb30…`, ihp-sg13g2 `c4b8b4e5…`);
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

All measured against the 3.1.0.dev1 copy above, in the container.

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

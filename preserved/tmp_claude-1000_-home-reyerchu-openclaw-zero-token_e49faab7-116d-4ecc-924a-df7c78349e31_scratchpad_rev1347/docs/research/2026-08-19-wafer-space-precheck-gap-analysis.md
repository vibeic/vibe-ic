# The shuttle precheck, run against a GDS we published

Status: measurement, not opinion. Every requirement below is cited to the file
and line that enforces it upstream. No requirement is quoted from memory.

NDA: the shuttle's PDK/foundry/node name is elided as `<PDK>` throughout. Layer
numbers and cell names are kept because they are the checkable content.

Upstream sources, both fetched 2026-08-19 at `main`:

    wafer-space/<PDK>-precheck            the submission gate itself
    wafer-space/<PDK>-project-template    the reference design + slot contract
    ghcr.io/wafer-space/<PDK>-precheck:main   official container, PDK bundled

A shuttle publishes the most honest definition of "done" available to us,
because it refuses for money. The precheck is that definition as a program.

---

## 1. THE EXPERIMENT — the real precheck, the real container, our real GDS

Subject: `benchmark-data/ic/spm/v1.9.96_<PDK>/phase3/stage4/gds/chip_top.gds`
sha256 `fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255`
(1,230,264 bytes; 46 cells; 23 populated layer/datatype pairs; ~100k shapes —
a genuine core layout, not a stub.)

Command (the container's own documented invocation, offline):

    docker run --rm --network=none -v $(pwd)/design:/data \
      ghcr.io/wafer-space/<PDK>-precheck:main \
      python3 precheck.py --input /data/chip_top.gds --top chip_top \
                          --dir /data --slot 1x1

Result: **FAILED at stage 3 of 16. Process exit 1.**

    Stage 1  Read the Layout        OK   (SHA256 of the submitted file logged)
    Stage 2  Check Top-Level Name   PASS "Design name 'chip_top' matches"
    Stage 3  Check Slot Size        FAIL subprocess exit 255
             [Error]: Layer 'GUARD_RING_MK' is not used. wafers.space
             requires a seal ring (guard ring) around the die.
    Stages 4-16                     NEVER RAN

Only three step directories exist under `runs/RUN_*/`, confirming the other
thirteen stages — GenerateID, Render, Density, ZeroArea, Antenna, Magic DRC,
KLayout DRC and their four Checkers, WriteLayout — were never reached.

A second published GDS,
`benchmark-data/ic/spm/v1.5.66_<PDK>/phase3/stage4/gds/spm.gds`
(sha256 `2915355c…`), fails identically at the same predicate (exit 255).

### 1.1 Per-predicate probe — what is hidden behind the early exit

`check_size.py` exits on its FIRST failure, so the verdict above names only the
seal ring. Re-running each predicate independently (predicates copied verbatim
from `check_size.py:8-109`; none altered) gives the full picture:

| predicate | `check_size.py` | v1.5.66 spm | v1.9.96 chip_top |
|---|---|---|---|
| origin at (0,0) | :36-38 | PASS | PASS |
| dbu == 0.001 um | :41-43 | PASS | PASS |
| Via5 (82/0) unused | :46-56 | PASS (0) | PASS (0) |
| MetalTop (53/0) unused | :46-62 | PASS (0) | PASS (0) |
| seal ring GUARD_RING_MK (167/5) | :65-74 | **FAIL (0 shapes)** | **FAIL (0 shapes)** |
| die size == slot size | :100-109 | **FAIL 237.0 x 237.0 um** | **FAIL 240.0 x 240.0 um** |
| Pad (37/0) present | `check_mask.drc:14` | **FAIL (0 shapes)** | **FAIL (0 shapes)** |
| 4 ID cells (CoB) | `generate_id.py:50-64` | **FAIL (all absent)** | **FAIL (all absent)** |
| exactly one top cell | `check_top.py:22-24` | PASS (1) | PASS (1) |
| zero-area polygons == 0 | `zero_area.drc` | PASS (0) | PASS (0) |

The smallest purchasable slot is 1936 x 5122 um. Our die is 240 x 240 um —
about 0.6% of the smallest slot's area, and 0.3% of the 1x1 slot's.

### 1.2 What this measures

The four predicates we pass — origin, dbu, metal-stack cap, single top cell —
are properties of the streamout tool, not of the design. Every predicate that
describes a *die* rather than a *core* fails.

**vibe-ic does not currently produce a submittable die. It produces a core.**
That is not a missing checker; it is a missing flow stage. A checker is still
worth building, because it would have said so on day one instead of at a
submission deadline.

Scope of the claim: measured on two artefacts of one design at two versions.
It is not established here that every vibe-ic design fails this way — but both
failures are structural (no frame layers exist at all), not design-specific.

---

## 2. THE CHECK LADDER, IN SUBMISSION-FAILURE ORDER

Order is `PrecheckFlow.Steps`, `precheck.py:439-470`. "Ours" was established by
grepping `programs/` (1178 files); each "none" line names the terms searched.

| # | Upstream check | file:line | Blocking? | vibe-ic program | Present |
|---|---|---|---|---|---|
| 1 | Input is `.gds` / `.gds.gz` / `.oas` | README; `precheck.py:628` | yes | `gds_size_check.py` takes any path | partial |
| 2 | SHA256 of submitted file recorded | `precheck.py:86-95` | log only | `provenance_logger.py`, `provenance_check.py` | present |
| 3 | Dummy datatypes 30/4,34/4,36/4,42/4,46/4,81/4 remapped to /0 before all checks | `read_layout.py:26-31` | implicit | `metal_fill_config_gen.dummy_datatype_for` *chooses* the datatype; nothing *verifies* the remap | partial |
| 4 | Exactly ONE top cell | `check_top.py:22-24` | yes | **none** — `gds_topcell_name_check.py` explicitly declines to fail on multiple tops ("a single GDS can legitimately carry multiple un-referenced tops"); `mixed_signal_top_lvs_run.py:398` enforces it only on the merged mixed-signal LVS artefact | **ABSENT** |
| 5 | Top cell name == declared name | `check_top.py:30-34` | yes | `gds_topcell_name_check.py` | present |
| 6 | Layout origin at (0,0) | `check_size.py:36-38` | yes | **none** (searched: origin, bbox origin, layout_origin) | **ABSENT** |
| 7 | dbu == 0.001 um | `check_size.py:41-43` | yes | **none** — GDS UNITS is parsed by `analog_hardmacro_gds_emit.um_per_dbu` and `analog_lef_gds_outline_check.py`, but never asserted; all other `UNITS` hits are DEF, not GDS | **ABSENT** |
| 8 | No metal above the 5-layer stack: 82/0 and 53/0 empty | `check_size.py:46-62` | yes | **none** — `gds_streamout_layermap_check.py` flags layers *no authority recognises*; a PDK-legal top-metal layer is recognised, so it is not an orphan. There is no layer-ceiling concept (searched: max_metal, metal_stack, MetalTop, top metal cap) | **ABSENT** |
| 9 | Seal ring layer GUARD_RING_MK (167/5) present | `check_size.py:65-74` | yes | **none** (searched: seal_ring, seal ring, guard_ring, GUARD_RING, GUARD_RING_MK, scribe, saw street. Only hits: `latchup_esd_spacing_check.py` screens guard-ring *cells* for latch-up; `floorplan_contract.py` parses the *words* "no seal ring" as a die-area qualifier. Neither examines a seal ring.) | **ABSENT** |
| 10 | Die bbox == exact slot size | `check_size.py:100-109` | yes | **none** — `gds_size_check.py` is BYTES not microns (`min_bytes = min_size_kb*1024`, :60,:108). `floorplan_contract.py` / `l19_pdk_floorplan_contract_check.py` check the *declared* contract in L-docs. `thermal_screen_check.py:218` / `floorplan_pdn_check.py:15` read DEF `DIEAREA`. No gate compares the shipped GDS bbox to a slot contract. | **ABSENT** |
| 11 | 4 ID cells present (CoB only) | `generate_id.py:50-64` | yes | **none** | **ABSENT** |
| 12 | Each ID cell instantiated exactly once at exact coordinates | `generate_id.py:89-91` | yes | **none** | **ABSENT** |
| 13 | ID string exactly 8 characters | `generate_id.py:45-47` | yes | **none** | ABSENT (cosmetic) |
| 14 | Pad openings (37/0) cover the golden pad mask | `check_mask.drc:14-23` | yes, CoB only | **none** (searched: pad_mask, golden_mask, pad_open, bond_pad, padring. Hits are RTL/constraint-level: `pad_drive_high_active_check.py`, `pad_side_constraint_check.py`, `fpga_pad_fanout_check.py` — none reads pad-opening geometry.) | **ABSENT** |
| 15 | Density deck | `precheck.py:454-455` | yes | `metal_layer_density_check.py`, `metal_fill_density_check.py` | present (report axis) |
| 16 | Zero-area polygons == 0 | `precheck.py:456-458`, `zero_area.drc` | yes | **none** — `mpw_precheck_result_gate.py` only *parses another shuttle's log*; `floorplan_pdn_check.py` means zero-area `DIEAREA`, a different quantity | **ABSENT** |
| 17 | Antenna deck | `precheck.py:460-461` | yes | `antenna_report_check.py`, `gds_antenna_deck_check.py`, ladder tier 3 | present |
| 18 | Magic DRC | `precheck.py:463-464` | **NO — see §4** | `drc_report_check`, `drc_vacuous_pass_check`, ladder tier 1 | we are stricter |
| 19 | KLayout DRC, decks `all,-antenna,-density,-cup` | `precheck.py:466-467`, `:576-580` | yes | same as 18 | present |
| 20 | LVS | — | **NOT RUN AT ALL** (`precheck.py:439-470`) | `lvs_tapeout_signoff_check.py` requires a genuine netgen match | we are stricter |

---

## 3. STAGE MAP — Reserve / Design / Sign-off / Submit vs our 44-step flow

| Shuttle stage | Artifact it needs | Our step that produces it | Status |
|---|---|---|---|
| Reserve | a chosen slot size, hence a fixed die W x H and a fixed IO count | `floorplan_contract.py` + L19 can carry a *design-declared* `DIE_AREA`; nothing maps a purchased slot to it | **no producer** |
| Design | core RTL -> placed & routed core | Phase 2 (steps 5-17) + Phase 3 PnR/CTS/route | complete |
| Design | **seal ring / frame** on 167/5 at the die edge | nothing | **no producer** |
| Design | **IO pad ring + bond-pad openings** on 37/0 matching the slot's pad template | `pad_side_constraint_check.py` constrains which *side* a pad is on; no pad-ring instantiation, no pad geometry | **no producer** |
| Design | die-ID cells at fixed coordinates | nothing | **no producer** |
| Sign-off | DRC / LVS / STA / antenna / density / IR / EM evidence | `signoff_ladder_run.py --mode tapeout` (15+ tiers), `signoff_audit.py` | complete, and stronger than theirs |
| Submit | one GDS that passes their precheck | `tapeout_signoff_check.py` (= `signoff_audit --mode tapeout`) gates our *reports*; nothing gates the *artefact* | **no producer** |

The pattern is one sentence: **our flow gates the reports it generated; the
shuttle gates the file you hand over.** Everything upstream re-derives its
verdict from the submitted layout. Our tapeout ladder trusts our own reports.

---

## 4. UPSTREAM CHECKS THAT CANNOT FAIL, OR BARELY CAN

Worth more to us than a feature we lack.

**4.1 The seal-ring check is a presence test standing in for a geometry test.**
`check_size.py:70` is `if GUARD_RING_MK_region.count() == 0`. It fails only when
layer 167/5 is completely empty. One polygon of any size, anywhere in the die,
passes. Nothing checks continuity, width (the slot contract says 26 um per
edge), enclosure, or adjacency to the die edge. A seal ring broken at one
corner — a routine pad-ring/PDN integration error — passes this gate and is
fabricated. This is the highest-consequence finding in the whole study,
because *neither side* catches it.

**4.2 Magic DRC runs and its verdict is discarded.**
The README lists "Runs magic DRC" among the checks the precheck performs.
`precheck.py:526-527` sets `"ERROR_ON_MAGIC_DRC": False`. The step executes,
produces a violation count, and cannot stop the flow. The project template says
the quiet part out loud (`librelane/config.yaml:108-110`): "Note: Passing magic
DRC is not required for the submission." So it is a *documented* advisory — but
the README presents it inside the list of checks performed, with no marker.

**4.3 The `cup` deck is disabled and `all` still reads as complete.**
`precheck.py:578`: `"decks": "all,-antenna,-density,-cup",  # disable CUP for
now`. Antenna and density are excluded because they run as their own steps.
`cup` is not: it is simply off. The PDK design manual states Circuit-Under-Pad
rules govern whether active circuitry may sit beneath a bond pad and that the
answer depends on the bonding type (ball/bump vs wedge). NOT DETERMINED: I did
not read the deck's contents, so I cannot say what it would have caught — only
that a named deck is off and the word `all` sits next to it.

**4.4 The pad-ring check is opt-in by the submitter.**
`CheckPadMask` and every ID-cell check are inserted only under `--cob`
(`precheck.py:595-598`, `generate_id.py:49,75`). A submission that does not
declare chip-on-board is never pad-checked at all. Similarly `--slot` is
submitter-declared: a wrong `--slot` makes `check_size` compare against the
wrong contract and pass. `--id` defaults to `FFFFFFFF` (`precheck.py:632`),
which satisfies the 8-character check.

**4.5 Cosmetic.** The zero-area step writes its reports as
`density.klayout.lyrdb` / `.json` (`precheck.py:316-317`) — copy-pasted from
the density step. The metric key is correct so the verdict is correct; only the
filename misleads. Each librelane step has its own `step_dir`, so there is no
collision. Named here only because we audit exactly this class in our own repo.

**4.6 Where upstream is simply weaker than us, and we must not copy it.**
The precheck runs NO LVS (`precheck.py:439-470` — the Steps list has no Netgen
or LVS step of any kind), no STA, no IR-drop, no EM, no DFT, no LEC. It is a
*manufacturability* gate: it answers "can this be made", never "does this
work". `signoff_ladder_run.py --mode tapeout` answers the second question
across 15+ tiers and explicitly refuses a `POWER_PIN_ONLY` LVS waiver
(`signoff_ladder_run.py:778-817`). Adopt their artefact-side rigour; keep ours.

---

## 5. GAPS RANKED BY CONSEQUENCE ON SILICON

**#1 — Broken seal ring reaches silicon. Class: DEAD CHIP.**
Neither gate can see it (§4.1; ours: absent, row 9). Dicing cracks propagate
into the die; moisture ingress kills it in the field. This is the only finding
where the failure is not caught by anyone.

**#2 — No bond pads / wrong pad openings. Class: DEAD CHIP.**
Measured: 0 shapes on 37/0 in both artefacts. A die with no pad openings has no
electrical access. Upstream catches it only under `--cob` (§4.4); we do not
catch it at all (row 14).

**#3 — Die geometry never checked against the slot. Class: SHIPS LATE.**
Measured: 240 x 240 um against a 3932 x 5122 um slot. Upstream *does* catch
this, so the cost is a rejected submission at the deadline — for a shuttle that
is the next run, i.e. months. Our whole Phase-3 chain cannot see it because no
gate ever opens the file it shipped (row 10). The capability exists 30 lines
away: `analog_lef_gds_outline_check.py` already parses a GDS bounding box, UNITS
and lower-left registration — it is wired only to analog hardmacros.

**#4 — Metal-stack ceiling, dbu, origin, single-top, zero-area. Class: SHIPS LATE.**
Five hard upstream rejects (rows 4, 6, 7, 8, 16) with no counterpart here. We
pass all five today by luck of the streamout tool, not by construction — none is
asserted anywhere, so a tool or config change flips them silently.

**#5 — Frame artefacts have no producer at all. Class: SHIPS LATE, repeatedly.**
Section 3: seal ring, pad ring, ID cells and the slot contract have no producing
step. A gate added without a producer converts a silent failure into a loud one,
which is the right first move — but it does not make a die submittable.

---

## 6. THE ONE PROGRAM

`programs/shuttle_submission_check.py` — a submission-artefact gate that reads
the shipped GDS and nothing else.

**It should WRAP, not reimplement.** The upstream precheck is maintained by the
party that refuses the die, ships an official offline container with the PDK
baked in, and changes when the shuttle changes. Reimplementing its DRC/density/
antenna decks would be a second source of truth that drifts. The wrap is also
already proven to work on this box: the run in §1 is exactly it.

Shape:

1. If the container is available, run it and parse the verdict — the same role
   `mpw_precheck_result_gate.py` plays for the other shuttle. Reuse that
   program's §4.05 discipline verbatim: absent evidence yields
   SKIPPED_CONDITION, never PASS.
2. If it is not available, run the *native* predicate set (rows 4-14 above)
   directly from the GDS. These need no PDK and no EDA tool — `pya` alone, as
   §1.1 demonstrates — so this arm is always runnable and is the one that would
   have caught our failure on day one.
3. Add the one predicate upstream lacks: **seal-ring continuity**, not presence.
   Merge 167/5, require a single closed annulus enclosing the core, of at least
   the contract width, on all four edges. This is the §4.1 gap, it is the only
   dead-chip finding nobody catches, and it is pure geometry — no PDK needed.

Checks in submission-failure order (the order §1 actually failed in), so the
first thing it reports is the first thing that would be rejected:

    top-cell count == 1  ->  top-cell name  ->  origin  ->  dbu  ->
    metal ceiling  ->  seal ring PRESENT  ->  seal ring CONTINUOUS  ->
    die bbox == slot  ->  pad layer present  ->  pad openings cover mask  ->
    ID cells present/placed  ->  zero-area polygons  ->
    [container arm] density -> antenna -> DRC

Declare it BLOCKING only for a submission target, and SKIPPED_CONDITION when no
slot contract is supplied — a core-only design must not be failed for not being
a die, but it must not be reported as tapeout-ready either.

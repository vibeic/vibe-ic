# Step 26.5ic — die finishing: what was measured, and what the external authority says

Measured 2026-08-19/20. Every number below came from running the tool named beside
it; nothing here is recalled.

Tools:
* `ghcr.io/wafer-space/gf180mcu-precheck:main` — the shuttle operator's OWN precheck
  container. (The brief named `:latest`; `:main` is the tag present on this host and
  is the one every result below was produced with. Stated because it is a difference.)
* `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff`
  — the pinned flow image, which is also where LibreLane was read.

---

## 1. THE REFUSAL, reproduced

Input: `benchmark-data/ic/spm/v1.9.96_gf180mcuD/phase3/stage4/gds/chip_top.gds`,
sha256 `fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255`.

    docker run --rm -v $HOME:$HOME ghcr.io/wafer-space/gf180mcu-precheck:main \
      python precheck.py --input <gds> --dir <rundir> --top chip_top --slot 1x1

    Stage 1  Read the Layout       OK
    Stage 2  Check Top-Level Name  PASS
    Stage 3  Check Slot Size       FAIL, exit 255
      [Error]: Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal
               ring (guard ring) around the die.
    PrecheckFlow — Stage 3 — Check Slot Size   2/16

Measured directly on the layout, confirming the refusal is about the die and not
about the reader: layer (167, 5) carries **0** shapes; the die is 240 x 240 um at
origin (0, 0), dbu 0.001.

## 2. THE FIX IS THE PDK'S OWN GENERATOR, AND IT MOVES THE REFUSAL

`die_finishing_gen` runs the PDK's `libs.tech/klayout/tech/scripts/sealring.py` and
verifies the result. Same input GDS, same checker:

    --- BEFORE (the published spm GDS) ---
    [Error]: Layer 'GUARD_RING_MK' is not used. …            rc=255
    --- AFTER (die_finishing_gen sealed it) ---
    Layout size:
    layout width:  240.0
    layout height: 240.0
    Expected slot size:
    slot width:  3932.0
    slot height: 5122.0
    [Error]: Layout size does not match slot size 1x1.       rc=255

**The seal-ring refusal is gone.** `check_size.py` now runs past that line, prints
the size it measured, and refuses for an unrelated and correctly attributed reason:
spm's 240 x 240 um die is not a wafer.space 1x1 slot (3932 x 5122 um). That is a
floorplan decision, not a seal-ring one, and nothing in this change addresses it.

STATED PRECISELY, because the stage counter does not move: `check_size.py` bundles
the seal-ring check and the slot-size check into ONE script, so the flow still stops
at "Stage 3 — Check Slot Size", 2/16. The refusal moved WITHIN stage 3, past the
GUARD_RING_MK line. It did not move past stage 3, and this document does not claim
it did.

### 2a. CLAUSE BY CLAUSE, measured with KLayout directly

`check_size.py` evaluates five clauses in order and stops at the first that
refuses, so "does stage 3 pass" is the wrong question — "WHICH CLAUSE refuses"
is the right one. Measured on the layouts themselves, not read off the
container's verdict, because a layer count cannot be satisfied by anything else
changing:

    clause                          BEFORE                    AFTER
    1 origin at (0,0)               True  (p1 = 0,0)          True  (p1 = 0,0)
    2 dbu == 0.001                  True                      True
    3 Via5 / MetalTop unused        True  (0 / 0)             True  (0 / 0)
    4 GUARD_RING_MK (167,5) used    0 shapes    -> REFUSES    1 shape, 14174 um2 -> PASSES
    5 layout size == slot size      240 x 240 um -> REFUSES   240 x 240 um -> REFUSES

Clause 4 is the one this step owns, and it flips. Clause 5 is untouched, before
and after, and is not this step's to fix.

ORIGIN CLAUSE, checked first because it fires BEFORE the seal-ring one: of four
published layouts, one is refused on an origin not at (0, 0), which would make a
correctly-inserted seal ring look like it did nothing. spm is not that layout —
its origin is exactly (0, 0) both before and after, as the table shows. No layout
was resized or moved to produce any result in this document.

The ring, measured: outer 0..240 um, inner 16..224 um — a 16 um band on all four
sides; 1 polygon on GUARD_RING_MK (167/5), 14174 um^2; 12 layers gained geometry;
the die bounding box is unchanged (the ring is drawn inside it).

## 3. WHAT THE NEXT WALL IS — probed, because it was worth knowing

The die-size refusal cannot be cleared by this step, so stages 4-16 were probed
instead with a SYNTHETIC die: the spm layout sealed at the full 1x1 slot size
(3932 x 5122 um), which is a correctly-sized sealed die and nothing more. **All 16
stages executed.** The full precheck stage list, read from `precheck.py`:

    1 ReadLayout   2 CheckTopLevel   3 CheckSize   4 GenerateID   5 Render
    6 Density      7 Checker.Density 8 ZeroAreaPolygons  9 Checker.ZeroArea
   10 Antenna     11 Checker.Antenna 12 Magic.DRC  13 Checker.MagicDRC
   14 KLayout.DRC 15 Checker.KLayoutDRC   16 WriteLayout

What refused, on the probe:

  * stage 4  GenerateID — **PASSED**, and this is the important one. See §4.
  * stage 7  8 KLayout density errors (deferred)
  * stage 13 5106 Magic DRC errors (warning)
  * stage 15 300602 KLayout DRC errors (deferred)

CAVEAT, and it is a large one: the probe is a 240 um design in a 3932 x 5122 um
canvas that is otherwise EMPTY. Density and DRC counts on a mostly-empty die are
dominated by that emptiness and say nothing about a real submission. What the probe
establishes is STRUCTURAL and is the part to rely on: with a seal ring and a correct
die size, the precheck reaches every stage, and the walls after stage 3 are density
and DRC — neither of which this step owns.

## 4. THE DIE-ID HALF IS CONDITIONAL, and the condition is default-OFF

Read out of the operator's own `generate_id.py`: the requirement for the four
`gf180mcu_ws_ip__{qrcode_id,shuttle_id,project_id,marker}` cells sits entirely
behind `if cob:`, and in `precheck.py` `--cob` is `action="store_true"` — default
**OFF**. Every precheck run in this document was therefore non-CoB, which is why
stage 4 passed with none of the cells present: on a non-CoB submission the
operator's own script is a silent no-op.

Consequences, which are why the gate is conditional:

  * an UNCONDITIONAL die-id gate would refuse correct non-CoB designs;
  * a gate that ignored the condition would credit a CoB design missing all four.

So `die_finishing_gen` reports the condition and its verdict:
`PRESENT` / `ABSENT` / `NOT_APPLICABLE` / `NOT_DETERMINED`, with the packaging
value that produced it. It reads the cell list and the packaging choice from
`die_finishing.die_id` in the PDK-bridge config and invents neither.

GAP, NAMED AND NOT TAKEN: this flow has no packaging declaration anywhere, and no
template-ingestion step. The four cells ship pre-built in the operator's project
template and are placed by it; ingesting that template decides the top-level source,
the macro list and the die geometry, which is Step 15's territory, not 26.5ic's.
Both are gatekeeper decisions. Until the packaging choice is declared, every design
reports `NOT_DETERMINED` for this half and the step reaches the flow's INCOMPLETE
tier — not clean, not red.

## 5. THE TRAP: A PDK SCRIPT THAT EXITS 0 AND WRITES NOTHING

Measured on the gf180mcuD PDK inside the pinned flow image (ciel version
`b344c97e…`): it ships `libs.tech/klayout/tech/scripts/sealring.py` but NOT the
`sealring_cells` PCell library that script imports. The script prints

    Error: Couldn't load the seal ring library.

and calls `sys.exit()` **with no argument** — so it exits **0** and writes no output
file. LibreLane's `KLayout.SealRing` trusts that exit status. A gate that read the
exit code would have recorded a seal ring that does not exist, on a PDK that ships
the script.

`die_finishing_gen` therefore diffs the two layouts and reports the exit code only
as evidence beside the measurement. On this PDK it FAILs with the reason named,
rather than passing.

(The acceptance runs above used the newer PDK that ships the library, which is
present in the operator's precheck container as ciel version `d658698b…`. That is an
environment difference, not a repository change, and no PDK file is vendored here.)

## 6. WHAT WAS TAKEN FROM UPSTREAM, AND WHERE THIS GOES FURTHER

Read out of `librelane/steps/klayout.py` in the pinned image.

TAKEN
  * the interface — `python3 <KLAYOUT_SEALRING_SCRIPT> --input --output
    --die-width --die-height`, with PDK_ROOT and PDK in the environment. Four
    flags, used unchanged.
  * the skip shape — upstream: "KLAYOUT_SEALRING_SCRIPT is unset. KLayout.SealRing
    may not be supported for the {PDK} PDK. This step will be skipped." Same shape,
    PDK named, plus the list of locations searched.
  * the second code path — `run_ihp_sg13g2` drives the script as a KLayout batch job
    AND sets `KLAYOUT_PATH` so the technology definition loads. Both reproduced.
  * generator and checker are SEPARATE, and the checker is what fails the flow
    (upstream: `KLayout.Density` then `Checker.KLayoutDensity`).
  * the placement — `"+Checker.KLayoutAntenna": KLayout.SealRing` in
    `librelane/flows/chip.py`. Step 26.5ic sits after 26 and before 31 for the same
    reason: the ring must go through DRC/LVS with the rest of the die.

FURTHER
  * upstream selects between its two code paths by PDK NAME. This reads the
    interface the script itself DECLARES (does it accept `--die-width`?). Measured
    on the two PDK scripts in the pinned image: the option appears once in the
    pya-cli one and zero times in the KLayout-batch one.
  * upstream derives the KLayout technology name by string-editing the PDK name.
    This reads `<name>` from the PDK's own `.lyt` — `sg13g2`, the same answer from
    the authority that owns it — and REFUSES when a PDK ships more than one.
  * upstream emits NO METRIC. `KLayout.SealRing` returns an empty `MetricsUpdate` on
    every path (three `return views_updates, {}` in the class), so a LibreLane run
    cannot distinguish a sealed die from one whose PDK had no script. This step
    writes `reports/phase3/die_finishing.json` on every path, with the seal-ring and
    die-identification halves in separate keys, and a finished-die DEF whose
    placement blockage is derived from the ring it actually measured.
  * upstream trusts the generator's exit status. See §5.

ABSENT UPSTREAM — reported as a finding, not as a gap in the search: LibreLane has
no die-identification step and no shuttle precheck. The `gf180mcu_ws_ip__*` cells
are the operator's, not the PDK's and not LibreLane's, so for that half there is
nothing to copy.

## 7. PER-PDK BEHAVIOUR, measured in the pinned image

    gf180mcuD    klayout sealring.py present   -> driven pya-cli
                 (its PCell library is absent in the image's PDK version; see §5)
    ihp-sg13g2   klayout sealring.py present   -> driven klayout-rd,
                 technology `sg13g2` read from the PDK's own sg13g2.lyt
    sky130A      NO klayout sealring script — it ships the magic-based generator,
                 and its LibreLane config.tcl leaves KLAYOUT_SEALRING_SCRIPT
                 COMMENTED OUT. Measured behaviour: DISCLOSED SKIP, rc 2, reason
                 naming the PDK and the path searched. Not a pass, not a crash.

NOT RUN: the `klayout-rd` path has never been executed end-to-end. Its argv
construction, its `KLAYOUT_PATH`, its form detection and its technology derivation
are each tested, but no ihp-sg13g2 die has been sealed by this code.

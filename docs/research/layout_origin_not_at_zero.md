# Why does `u_hawaii_adc`'s sky130A GDS start at (-4.5, -223.305)?

Research note. A determination, not a fix. No program changed, no gate written,
no geometry moved.

**Answer: C. THE WRONG TOP CELL.** `ldo` is a sub-block, and the file in the
chip-GDS position is a byte-correct stream of it. The layout is not defective
and the streamer is not defective: every negative coordinate in the file is
present, to the nanometre, in the Magic database it was written from, and the
block's own LEF *declares* the offset (`ORIGIN 4.500 223.305 ;`). What is wrong
is what ended up in the chip position. This design never produced a chip GDS at
all — its whole digital backend is `SKIPPED-CONDITION` in its own run-time
audit — and the artefact at `phase3/stage4/gds/ldo.gds` was manufactured at
PUBLISH time by a "largest `.gds` anywhere under the run" fallback that picked
an analog hardmacro.

Determined 2026-08-20 on host 8HD-6, against
`benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A`.

---

## 1. What is actually in the file

Two tool images, both resolved rather than remembered
(`programs/_eda_image.py`):

* `ghcr.io/vibeic/vibeic-eda:0.3.16`
  (`sha256:f6b09c1388c6efe96bae562ec1b0454beef4736096feb0b1bbc2d3af6b6123c6`),
  KLayout 0.30.10 via the `klayout.db` pymod;
* `ghcr.io/wafer-space/gf180mcu-precheck:latest`
  (`sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f`),
  read-only, for the shuttle's own rule text in §4.

`--skip` is the first argument AFTER the image name: the image entrypoint is the
iic-osic-tools launcher, and `docker run --skip …` is rejected by docker itself.

```
$ docker run --rm -v ~/_jlayout/work:/work \
    -v ~/vibe-ic/benchmark-data/ic/u_hawaii_adc:/dsn:ro \
    ghcr.io/vibeic/vibeic-eda:0.3.16 \
    --skip bash -lc 'python3 /work/hier.py /dsn/v1.9.86_sky130A/phase3/stage4/gds/ldo.gds'
```

where `hier.py` reads the layout and prints top cells, per-cell bounding boxes
and instance transforms. Output:

```
DBU       : 0.001
N_CELLS   : 7
N_TOPCELLS: 1

top cell: 'ldo'
  bbox dbu : (-4500, -223305) .. (328080, 240110)
  bbox um  : (-4.5000, -223.3050) .. (328.0800, 240.1100)
  size um  : 332.5800 x 463.4150
  child cells (direct): 6
  hierarchy levels below: 1

  cap_cap_mim_m3_1_w27p5_l27p5        ( -14.830,  -13.950)..(  14.830,  13.950)  parents=2
  dev_nfet_w16_l1                     (  -1.425,   -8.995)..(   1.425,   8.995)  parents=1
  dev_nfet_w20_l0p5                   (  -1.175,  -10.995)..(   1.175,  10.995)  parents=2
  dev_pfet_w20_l0p5                   (  -1.230,  -11.095)..(   1.230,  11.095)  parents=2
  dev_pfet_w60_l0p15                  (  -1.055,  -31.095)..(   1.055,  31.095)  parents=12
  ldo                                 (  -4.500, -223.305)..( 328.080, 240.110)  parents=0  top=True
  res_res_high_po_1p41_w1p41_l440p9   (  -1.480, -223.305)..(   1.480, 223.305)  parents=2
```

Seven cells. One top cell, named `ldo`. Two levels of hierarchy: a top and six
device primitives. No standard-cell rows, no digital core, no pad ring, no
second analog block.

Every child cell's own box is symmetric about (0,0) — Magic's device generators
emit devices centred on their own origin — and every one of the 21 instances is
placed with a **zero Y translation**:

```
  res_res_high_po_1p41_w1p41_l440p9  trans=r0 307975,0   (306.495,-223.305)..(309.455,223.305)
  res_res_high_po_1p41_w1p41_l440p9  trans=r0 322045,0   (320.565,-223.305)..(323.525,223.305)
  dev_pfet_w60_l0p15  x12            trans=r0    ...,0   (    ... ,-31.095)..(    ... , 31.095)
  cap_cap_mim_m3_1_w27p5_l27p5 x2    trans=r0    ...,0   (    ... ,-13.950)..(    ... , 13.950)
  dev_nfet_w16_l1                    trans=r0   1480,0   (  0.055 , -8.995)..(  2.905 ,  8.995)
```

So `-223.305` is not a lost translation. It is exactly the half-height of the
446.61 µm poly resistor cell, sitting on its own centre at y = 0.

`-4.5` on X is top-level metal drawn directly in `ldo` (the leftmost *instance*
begins at x = +0.055):

```
  layer 70/20 (met3 drawing): 13 shapes  bbox=(-4.500,  -0.250)..(328.080, 240.110)
  layer 70/16 (met3 pin)    :  5 shapes  bbox=(-4.000, 229.110)..( -3.000, 240.110)
  layer 67/20 (li1 drawing) : 19 shapes  bbox=(-2.000,-220.450)..(320.860,  -5.640)
```

The block's five ports sit at x = -4.0 … -3.0 µm, deliberately outside x = 0.

## 2. The stream is faithful — this is not a GDS-writer defect (not B)

Source: `v1.9.86_sky130A/phase3/analog/ldo/ldo.mag`, byte-identical to
`layout.mag` beside it (`diff -q` → identical). Header `magscale 1 2` with
sky130A → 1 internal unit = 5 nm.

```
$ sed -n '1581,1588p' ldo.mag
use res_res_high_po_1p41_w1p41_l440p9  R1
transform 1 0 61595 0 1 0        # 61595 x 5nm = 307975 nm  == GDS  r0 307975,0
box -307 -44672 307 44672
use res_res_high_po_1p41_w1p41_l440p9  R2
transform 1 0 64409 0 1 0        # 64409 x 5nm = 322045 nm  == GDS  r0 322045,0
```

The top-level metal already reaches negative X in the source, to the same
micron:

```
$ awk '/^<< metal3 >>/{f=1;next} /^<< /{f=0} f&&/^rect/{ ...min/max... }' ldo.mag
metal3 mag units: x -900..65616   y -50..48022
metal3 um (x5nm): x -4.500..328.080   y -0.250..240.110
```

`-4.500 .. 328.080` is exactly the GDS top-cell X extent. And the ports:

```
$ sed -n '1589,1600p' ldo.mag
<< labels >>
rlabel metal3 -800 47622 -600 47722 0 IOVDD      # x -4.000 .. -3.000 um
port 1 nsew
rlabel metal3 -800 46122 -600 46222 0 VSS
rlabel metal3 -800 47322 -600 47422 0 VREF
rlabel metal3 -800 47922 -600 48022 0 VOUT
rlabel metal3 -800 45822 -600 45922 0 VBIAS
```

Five rlabels at x = -4.0 … -3.0; the GDS carries exactly five shapes on 70/16.
(Magic's sky130A layer `metal3` is GDS 70/20, and its pin purpose is 70/16;
`locali` is 67/20, `metal1` 68/20, `metal2` 69/20, `metal4` 71/20.)

Transform for transform, label for label, nanometre for nanometre, the GDS is
what the Magic database says. **No fork change is warranted and none was made.**

## 3. The block declares its own offset — legal as a macro

`phase3/analog/hardmacro/ldo/ldo.lef`:

```
MACRO ldo
  CLASS BLOCK ;
  FOREIGN ldo ;
  ORIGIN 4.500 223.305 ;
  SIZE 332.580 BY 463.415 ;
```

`ORIGIN` is LEF's declared offset from the macro's lower-left to its origin, and
`SIZE` is the measured extent of §1 to the nanometre. This is precisely the
mechanism by which a macro tells a placer "my geometry is not at my origin,
compensate by this much". Nothing about the frame is undeclared.

That is the whole force of the finding: **this file is a correct macro that was
put in the die position, where the same numbers are not legal.**

## 4. Is a negative-origin GDS legal for sky130A? No PDK rule found.

Looked in the PDK first:

```
$ docker run --rm ghcr.io/vibeic/vibeic-eda:0.3.16 --skip bash -lc \
   'grep -rniE "\borigin\b" /foss/pdks/sky130A/libs.tech/klayout/ \
                            /foss/pdks/sky130A/libs.tech/magic/*.tech'
/foss/pdks/sky130A/libs.tech/klayout/python/import_netlist/import_netlist.py:62:
    # Add an offset to the position to account for the origin
```

One hit, in a netlist-import utility, nothing to do with sign-off. The sky130A
decks — `sky130A_mr.drc` (release `2024.2.11_01.09`), `sky130A.lydrc`,
`macros/run_drc_{feol,beol,full}.lydrc`, `zeroarea.rb.drc` — contain no rule
naming the origin or any absolute coordinate. That is structural rather than an
accident of the grep: a DRC rule is a relation between shapes, so a rule deck is
translation-invariant by construction and cannot express "the box must start at
(0,0)".

**So: I could not find a sky130A PDK rule that a negative origin violates, and I
do not believe one exists.** DRC-wise the file is legal, and the run says so
(`phase3/analog/ldo/drc_clean.flag`).

The rule that does exist belongs to a **shuttle operator**, quoted from the
operator's own container rather than from anyone's paraphrase —
`/workspace/scripts/klayout/check_size.py`:

```python
    # Check origin
    if ly.top_cell().dbbox().p1 != pya.DPoint(0, 0):
        print("[Error]: Layout origin is not at (0, 0)")
        sys.exit(-1)
```

and, in the same container, `/workspace/scripts/klayout/check_top.py`:

```python
    if len(ly.top_cells()) > 1:
        print(f"[Error] More than one top-level cell in {input}!")
        sys.exit(1)
    if ly.top_cell().name != top:
        print(f"[Error] Top-level cell name '{ly.top_cell().name}' does not "
              f"match expected name '{top}'!")
        sys.exit(1)
```

**Scope of that quote, stated so it is not over-read:** wafer.space is a
**gf180mcu** shuttle. It is not the authority for a sky130A die. The only
sky130-side operator this tree knows is `efabless_open_mpw`
(`programs/tapeout_readiness_check.py:327`), recorded `status=RETIRED` — "the
shuttle operator ceased operating in 2025" — and its ladder (license, makefile,
default, documentation, consistency, gpio_defines, xor, magic_drc,
klayout_feol/beol/offgrid, lvs, oeb) has **no origin step and no top-cell step
at all**; it constrains the frame by XOR against a golden wrapper instead.

The accurate three-part answer:

| Asked of | Verdict |
|---|---|
| the sky130A PDK | **no rule found.** Legal as far as any deck in the PDK can say. |
| this file as a HARDMACRO | **legal and correctly declared** — `ORIGIN 4.500 223.305` (§3). |
| this file as a DIE | **refused** by the one live shuttle whose rule is executable, and **unadjudicated** by any live sky130 operator, because there is not one. |

## 5. What the chip was supposed to be

`phase3/analog/analog_block_list.json` names two analog blocks and quotes the
design's own input docs:

```
  "name": "delta_sigma", "count": 6, "multiplicity": 6
     evidence: input/docs/L1_DATASHEET.md
     "| Channels | **6** identical incremental delta..."
  "name": "ldo",         "count": 1, "multiplicity": 1
     evidence: input/docs/L9_CONSTRAINTS.md
     "## Floorplan | Core die (no seal ring) | 1300 x 1300 um |
                   | With seal ring | ~1480 x 1480 um |
                   | Channel layout | 6 identical modulator copies (array);
                                       1 with adjacent LDO |
                   | Pad ring | analog IN/OUT + supply pa..."
```

A 1300 × 1300 µm core carrying six modulators, one LDO and a pad ring. The
streamed file is 332.58 × 463.415 µm, is one of the seven analog instances, and
has neither pad ring nor digital. It is ~8 % of the core area.

## 6. How the file got into the chip position

Two distinct GDS existed in the entire source run, and both are analog
hardmacros:

```
$ find benchmark-data/ic/u_hawaii_adc -name '*.gds' -printf '%p  %s bytes\n'
.../v1.9.86_sky130A/phase3/stage4/gds/ldo.gds                        641262 bytes
.../v1.9.86_sky130A/phase3/analog/hardmacro/delta_sigma/delta_sigma.gds 111096 bytes
.../v1.9.86_sky130A/phase3/analog/hardmacro/ldo/ldo.gds              641262 bytes

$ sha256sum <the three>
369719cff9eb079a7f47dceef4bd05320616c0ca0955ca55cf5d8c26a56f4e87  stage4/gds/ldo.gds
369719cff9eb079a7f47dceef4bd05320616c0ca0955ca55cf5d8c26a56f4e87  analog/hardmacro/ldo/ldo.gds
055a0412a92376f03a969bc91b0c3db3341d52c0449088efd2c7dd9881a9ae1a  analog/hardmacro/delta_sigma/delta_sigma.gds
```

The chip GDS is byte-identical to the LDO hardmacro. Step 37 ("GDSII output")
never ran — the run's own audit, captured at run time and authoritative for a
published cell:

```
$ python3 -c "import json; d=json.load(open('reports/audit/phase23_completion_audit.json')); \
              print(d['verdict'], d['step_counts'])"
PASS {'PASS': 8, 'FAIL': 0, 'MISSING': 0, 'WAIVED': 0, 'DEFERRED-BY-UPSTREAM': 0,
      'SKIPPED-CONDITION': 53, 'SKIPPED-SETUP-REQUIRED': 0, 'VACUOUS_PASS': 2,
      'STRUCTURE-ONLY': 0, 'INCOMPLETE': 0}
```

`reports/final_summary.md`, same run: Stage 3 (PD) **0 / 18**, Stage 4
(Sign-off) **0 / 7**, Analog A1–A9 **8 / 9**. The design is analog-only; the
digital backend and all of stage 4 are `SKIPPED-CONDITION`.

(The *absence* of `phase3/stage3/` and of any DEF is not independent evidence of
that — `flow_compliance_check.published_tree_note()` records that publishing
deliberately excludes `phase3/stage3/*`. The run-time audit above is the
evidence.)

So what wrote `phase3/stage4/gds/ldo.gds`? The publisher.
`programs/benchmark_evidence_publish.py:495`:

```python
def _find_gds(run_dir: Path, explicit: Optional[Path]) -> List[Path]:
    """--gds wins; else every *.gds directly in the canonical streamout dir
    phase3/stage4/gds/ ...; else, as a fallback, the single largest *.gds
    anywhere under the run."""
    ...
    anywhere = sorted((p for p in run_dir.rglob("*.gds") if p.is_file()),
                      key=lambda p: p.stat().st_size, reverse=True)
    if anywhere:
        return [anywhere[0]]
```

The source run had no `phase3/stage4/gds/`, so the fallback fired and took the
largest `.gds` anywhere: `ldo.gds` (641262 B) over `delta_sigma.gds`
(111096 B). It was copied into the chip-GDS position and manifested.

The publisher's own record proves it. `LAYOUT_ROUTING.txt` at the cell root
lists every layout artefact found under the source run, one line per **blob**:

```
phase3/analog/hardmacro/delta_sigma/delta_sigma.gds 111096B sha256:055a0412... STAGED in-cell
phase3/analog/hardmacro/ldo/ldo.gds                 641262B sha256:369719cf... STAGED in-cell
phase3/analog/hardmacro/ldo/ldo.gds                 641262B sha256:369719cf... STAGED in-cell
```

`ldo.gds` appears **twice** — staged once as the hardmacro it is, once as the
chip GDS it is not. There never was a chip GDS.

## 7. The gate that should have caught it, and where it belongs

### 7a. The gate exists, is tested, and is not wired

`programs/gds_topcell_name_check.py` — a pure-Python GDSII record walk that
finds the structure defined-and-never-referenced and compares it by name.
Measured on this exact artefact:

```
$ python3 programs/gds_topcell_name_check.py \
    --gds-file .../phase3/stage4/gds/ldo.gds --top-name u_hawaii_adc
  ERROR TOPCELL_NAME_MISMATCH: --top-name 'u_hawaii_adc' is NOT defined as a
  structure in the GDS
  details: defined structures: ['cap_cap_mim_m3_1_w27p5_l27p5',
    'dev_nfet_w16_l1', 'dev_nfet_w20_l0p5', 'dev_pfet_w20_l0p5',
    'dev_pfet_w60_l0p15', 'ldo', 'res_res_high_po_1p41_w1p41_l440p9']
  "pass": false
rc=1                                  <-- RED on the design's own name

$ ... --top-name ldo
  "pass": true
rc=0                                  <-- GREEN on the sub-block's name
```

It discriminates. It has a test (`programs/tests/test_gds_topcell_name_check.py`).
And it appears **nowhere** in the flow:

```
$ for p in gds_topcell_name_check chip_gds_canonical_real_file_check \
           general_precheck gds_substance_check gds_port_label_check; do
    printf "%-38s program=%s flow_mentions=%s\n" "$p" \
      "$([ -f programs/$p.py ] && echo yes || echo NO-FILE)" \
      "$(grep -c "\b$p\b" flow/phase1_phase2_phase3.yaml)"; done
gds_topcell_name_check                 program=yes flow_mentions=0
chip_gds_canonical_real_file_check     program=yes flow_mentions=0
general_precheck                       program=yes flow_mentions=5
gds_substance_check                    program=yes flow_mentions=1
gds_port_label_check                   program=yes flow_mentions=2
```

Written, tested, never wired — the same shape the flow's own comment at
`flow/phase1_phase2_phase3.yaml:2536` records for `analog_lef_gds_outline_check`.

### 7b. Step 37 has four clauses and not one of them asks what cell is in the file

Step 37's gate is `files_exist: ["phase3/stage4/gds/*.gds"]` plus
`gds_size_check`, `gds_substance_check`, `gds_port_label_check` and
`provenance_check`. Measured against a copy of this cell:

```
gds_size_check      --gds-file .../ldo.gds  -> pass:true, 626.23 KB >= 100 KB          rc=0
gds_substance_check .                       -> PASS: 7 structures, 10023 elements,
                                               14 layers, design floor N/A (no DEF)    rc=0
gds_port_label_check .                      -> VACUOUS_PASS: no DEF names a structure
                                               present in this GDS
                                               (structures=7, tops=ldo; DEFs offered=none)  rc=2
provenance_check .  --output=... --tool=... -> FAIL: no entry declares it as an output rc=1
```

Three of the four wave it through. The fourth refuses on the missing
`provenance.jsonl` — on the FILE, never on the cell. And `files_exist` is a
**glob**: `phase3/stage4/gds/*.gds` accepts any basename, so `ldo.gds` standing
in for `u_hawaii_adc.gds` is invisible to it.

### 7c. The one gate that does ask cannot answer, and says so

`general_precheck` (step 37.5self) has the rungs. Run directly on this cell:

```
 1 KLayout.ReadLayout              PASS            read 7 structure(s), 9976 polygon(s)
 3 KLayout.CheckTopLevel           NOT_DETERMINED  the top cell is 'ldo' and `top_cell`
                                                   was not declared, so there is nothing
                                                   to compare it against
 4 KLayout.CheckSize               NOT_DETERMINED  the layout's extent is
                                                   [-4.5, -223.305, 328.08, 240.11], and
                                                   `deliverable` was not declared. A DIE
                                                   must start at the declared origin;
                                                   a HARDMACRO need not
 8 Checker.KLayoutZeroAreaPolygons PASS            0 zero-area polygons out of 9976
rc=1   declaration_answered=0/18
```

That is the honest answer — NOT_DETERMINED, never "clean" — but it is still not
a catch. `general_precheck` compares against
`input/submission_template/tapeout_declaration.json`, a **human answer** written
by step 0.5ic on one of three mutually exclusive routes. This run was on none of
them, so the comparand did not exist. And 37.5self sits *downstream of step 37*,
which never ran.

### 7d. Where the gate belongs

Two places, in this order. **Do not write either here — this row is a
determination.**

1. **At the publisher, `benchmark_evidence_publish._find_gds` (line 495).** This
   is where THIS artefact was born. The "largest `.gds` anywhere under the run"
   fallback must not be able to promote a hardmacro into the chip-GDS position.
   A run that streamed no chip GDS should be published with **no** chip GDS and
   a stated reason, not with the biggest thing lying around. The publisher's own
   `LAYOUT_ROUTING.txt` already has the vocabulary for that (`NOT_PUBLISHED`,
   with the reason recorded).

2. **As a fifth clause of step 37's own gate**, `gds_topcell_name_check`, with
   `--top-name` sourced from a **machine fact the flow already holds** — the
   DEF's own `DESIGN <name> ;` in `phase3/stage3/pnr/routed.def` (which
   `gds_port_label_check` already reads for exactly this pairing), or the
   synthesis top from steps 9/14 — and **not** from the tape-out declaration.
   The declaration is a human answer that exists on only one of three routes;
   the top module name is known unconditionally on the chip path, which is
   precisely where step 37 lives. Wired there, the same class of defect is
   caught on a live run, where the publisher is not involved at all.

A note for whoever opens the fix row: the two are not redundant. (1) stops a
false chip artefact from entering `benchmark-data`; (2) stops a real run from
streaming a sub-block as the chip. This cell needed (1). A converged run needs
(2).

## 8. What was NOT done, deliberately

Nothing was translated to the origin. Header rule 5, and the reason it exists:
had the geometry been moved, a wrong block would look like a right chip, and the
real defect — that a hardmacro occupies the chip-GDS position of a design that
never had one — would become invisible and ship. The numbers above are the
artefact's own.

## 9. Reproducing the numbers

The brief's figures — top cell `ldo`, bbox origin (-4.5, -223.305) — reproduced
**exactly**, from the raw GDS, with a tool that had never seen the claim. There
is no discrepancy to report.

They also match, to the nanometre, two places where this tree had already
recorded them independently: `programs/general_precheck.py` (lines 68–88) and
`programs/_gds_geometry.py` (lines 38–50), both of which cite this artefact by
sha256 as their known positive.

# Where do the four `gf180mcu_ws_ip__*` cells come from?

Research note. No program, no gate. Blocks half of Step 26.5ic.

**Answer: A. SHIPPED.** The four cells are shipped, as pre-built hardmacros
(GDS + LEF + LIB + blackbox Verilog), by the shuttle operator's project template
repository. The submitter does not generate them and does not draw them — the
submitter *starts from the template* and must not delete them.

    https://github.com/wafer-space/gf180mcu-project-template
    at ip/gf180mcu_ws_ip__{qrcode_id,shuttle_id,project_id,marker}/
    HEAD measured: 0de7e394337a1f7f5303ac7a3681bf2481b58176 ("ci: pull git submodules (#75)")
    License: Apache-2.0. Author: Leo Moser <leo.moser@pm.me> (AUTHORS.md)

Our flow's real gap is therefore a **template-ingestion step**, not a generator.
This matches the efabless precedent in item 4 of the brief: caravel shipped the
user-project-wrapper with the id cells pre-placed; wafer.space works the same way.

---

## The decisive question: does `generate_id.py` create the cells?

**No. It only places and edits them.** Measured, reading the script end-to-end
inside the authoritative image.

```
$ docker run --rm --entrypoint bash ghcr.io/wafer-space/gf180mcu-precheck:latest \
    -c 'cat /workspace/scripts/klayout/generate_id.py'
```
Image digest `sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f`.

Every reference to the four cells is a *lookup*, never a create:

```python
 68    qrcode_id_cell  = ly.cell("gf180mcu_ws_ip__qrcode_id")
 69    shuttle_id_cell = ly.cell("gf180mcu_ws_ip__shuttle_id")
 70    project_id_cell = ly.cell("gf180mcu_ws_ip__project_id")
 71    marker_cell     = ly.cell("gf180mcu_ws_ip__marker")
```

`pya.Layout.cell(name)` returns `None` when the cell is absent. Every subsequent
write is guarded — `if qrcode_id_cell:` (118), `if project_id_cell:` (183),
`if shuttle_id_cell:` (193), `if marker_cell:` (239). So a layout that lacks the
cells is written back **unchanged and unmarked**, with no error, whenever the CoB
switch is off.

What the script *does* generate is only the **content** — from a PCell library
(`gf180mcu_ws_pcells`, at `/workspace/scripts/klayout/pcell_library/`, shipped in
the image) — and then copies it into cells that must **already exist at exactly
the right size**:

```python
120        assert qrcode_id_cell.bbox() == qrcode_id_cell_tmp.bbox()
123        qrcode_id_cell.clear()
126        qrcode_id_cell.copy_tree(qrcode_id_cell_tmp)
```
plus the same clear/copy_tree pair for `project_id` (185-191), `shuttle_id`
(195-201) and `marker` (241-247).

The id string is split — `shuttle_id = id[0:4]`, `project_id = id[4:8]` (177-178)
— which is why the `--id` must be exactly 8 characters (45-47).

## Scoping nuance: this is enforced ONLY under `--cob`

The presence checks and the coordinate assertions are both inside `if cob:`:

```python
 49    if cob:
 50        if not ly.has_cell("gf180mcu_ws_ip__qrcode_id"):
 51            print("Error: Couldn't find ID cell: 'gf180mcu_ws_ip__qrcode_id'.")
 52            sys.exit(1)
      ... same for shuttle_id (54), project_id (58), marker (62)

 75    if cob:
 76        for cell, coords in [...]:
 90            assert (len(cell_insts) == 1), f"... must be instantiated exactly once."
 91            assert (cell_insts[0].dbbox() == pya.DBox(*coords)), f"... must have coordinates ..."
```

and `--cob` defaults to OFF:

```python
632    parser.add_argument("--id", default="FFFFFFFF", help="The ID to use for this chip.")
633    parser.add_argument(
634        "--cob",
635        action="store_true",          # <- default False
636        help="Use the CoB (Chip-On-Board) packaging option (extra checks).",
637    )
```

So: a **non-CoB** submission passes precheck with no ID cells at all, and
`generate_id.py` is a silent no-op on it. A **CoB** submission is hard-blocked
without all four. Confirmed by the image's own README:

> `/workspace/README.md:9-13`
> ```
>  9  - If the CoB switch is selected:
> 10    - Ensures the `gf180mcu_ws_ip__qrcode_id`, `gf180mcu_ws_ip__shuttle_id`,
>        `gf180mcu_ws_ip__project_id` and `gf180mcu_ws_ip__marker` cells exists in the layout.
> 11    - Ensures there is only one instance of each and their location is as in the project template.
> 12    - Replaces their contents with the value of the `--id` argument.
> ```

Line 11 — "**their location is as in the project template**" — is the sentence that
names the source artefact, and line 12 confirms the division of labour: the
submitter supplies the placeholders, wafer.space replaces the contents.

## The template ships them — measured

```
$ gh api repos/wafer-space/gf180mcu-project-template/git/trees/main?recursive=1 --jq '.tree[].path'
```
returns, among others:

```
ip/gf180mcu_ws_ip__qrcode_id/{gds,lef,lib,vh}/gf180mcu_ws_ip__qrcode_id.*
ip/gf180mcu_ws_ip__shuttle_id/{gds,lef,lib,vh}/gf180mcu_ws_ip__shuttle_id.*
ip/gf180mcu_ws_ip__project_id/{gds,lef,lib,vh}/gf180mcu_ws_ip__project_id.*
ip/gf180mcu_ws_ip__marker/{gds,lef,lib,vh}/gf180mcu_ws_ip__marker.*
ip/gf180mcu_ws_ip__logo/{gds,lef,lib,vh,image,script}/...      # a 5th, optional
```

Each is a full hardmacro. The Verilog view is a blackbox with no ports, i.e. the
cells are pure layout fixtures carried through synthesis:

```verilog
// ip/gf180mcu_ws_ip__marker/vh/gf180mcu_ws_ip__marker.v
(* blackbox *)
module gf180mcu_ws_ip__marker;
endmodule
```

### The measured GDS geometry matches the pinned coordinates exactly

Measured with the precheck image's own KLayout 0.30.9 over the cloned template:

```
$ docker run --rm -v "$PWD":/w \
    --entrypoint /nix/store/dljmpck53kb6zxhvd73b688286b0kwkn-klayout-0.30.9/bin/klayout \
    ghcr.io/wafer-space/gf180mcu-precheck:latest -b -r /w/dump.py

gf180mcu_ws_ip__logo.gds        cell=gf180mcu_ws_ip__logo       bbox=(0,0)-(143.250,143.250) w=143.250 h=143.250
gf180mcu_ws_ip__marker.gds      cell=gf180mcu_ws_ip__marker     bbox=(0,0)-(245.000,245.000) w=245.000 h=245.000
gf180mcu_ws_ip__project_id.gds  cell=gf180mcu_ws_ip__project_id bbox=(0,0)-(195.500,59.500)  w=195.500 h=59.500
gf180mcu_ws_ip__qrcode_id.gds   cell=gf180mcu_ws_ip__qrcode_id  bbox=(0,0)-(142.800,142.800) w=142.800 h=142.800
gf180mcu_ws_ip__shuttle_id.gds  cell=gf180mcu_ws_ip__shuttle_id bbox=(0,0)-(195.500,59.500)  w=195.500 h=59.500
```

The template pins the placement in `librelane/macros/macros_5v.yaml`, and the
comments there state the requirement in the operator's own words:

```yaml
 2    # required: will be replaced with actual content
 3    gf180mcu_ws_ip__qrcode_id:
14        qrcode_id:
15          location: [26, 26]
16          orientation: N
18    # required: will be replaced with actual content
19    gf180mcu_ws_ip__shuttle_id:
30        shuttle_id:
31          location: [26, 175.6]
32          orientation: E
34    # required: will be replaced with actual content
35    gf180mcu_ws_ip__project_id:
46        project_id:
47          location: [175.6, 26]
48          orientation: N
50    # required: top right corner marker
51    gf180mcu_ws_ip__marker:
62        marker:
63          location: ["expr::($DIE_AREA[2] - (245 + 36))", "expr::($DIE_AREA[3] - (245 + 36))"]
64          orientation: N
```

Composing the measured cell size with the pinned location reproduces
`generate_id.py`'s asserted boxes (lines 76-88) **exactly**, all four:

| cell | measured size | location / orientation | derived bbox | asserted at generate_id.py:78-87 |
|---|---|---|---|---|
| `qrcode_id`  | 142.8 x 142.8 | [26, 26] N       | (26, 26)-(168.8, 168.8)   | `(26,26,168.8,168.8)` ✅ |
| `shuttle_id` | 195.5 x 59.5  | [26, 175.6] **E** | (26, 175.6)-(85.5, 371.1) | `(26,175.6,85.5,371.1)` ✅ |
| `project_id` | 195.5 x 59.5  | [175.6, 26] N    | (175.6, 26)-(371.1, 85.5) | `(175.6,26,371.1,85.5)` ✅ |
| `marker`     | 245 x 245     | [W-281, H-281] N | (W-281, H-281)-(W-36, H-36) | `width-36-245 .. width-36` ✅ |

`shuttle_id` is the one that looks wrong until you notice `orientation: E` — the
195.5 x 59.5 cell is rotated 90 degrees to 59.5 x 195.5, which is what makes
`(26,175.6)-(85.5,371.1)` come out right. A generator that ignored the
orientation would fail assertion 91.

The sizes also match the script's own hard-coded constants: `qrcode_width =
142.8` (95), `text_id_width = 195.5` / `text_id_height = 59.5` (133-134),
`"width": 245` for the marker (211).

### The template instantiates them, with an explicit do-not-remove

```systemverilog
// src/chip_top.sv:264-271
    // Do not remove, necessary for tapeout
    (* keep *) gf180mcu_ws_ip__qrcode_id qrcode_id ();
    (* keep *) gf180mcu_ws_ip__shuttle_id shuttle_id ();
    (* keep *) gf180mcu_ws_ip__project_id project_id ();
    (* keep *) gf180mcu_ws_ip__marker marker ();

    // wafer.space logo - can be removed if desired
    (* keep *) gf180mcu_ws_ip__logo wafer_space_logo ();
```

The contrast between the two comments is itself the spec: the four are mandatory,
the logo is optional. All five are also listed in `librelane/config.yaml:58-62`.

---

## Where I looked — FOUND / ABSENT per the brief

**1. The precheck image — FOUND (script), ABSENT (cells).**
`ghcr.io/wafer-space/gf180mcu-precheck:latest`, pulled fresh, digest
`sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f`.
The image ships `generate_id.py` and the `pcell_library` that renders the
*content*, but **no `gf180mcu_ws_ip__*` layout artefact of any kind**:

```
$ find / -xdev \( -iname "*.gds*" -o -iname "*.oas*" -o -iname "*.lef" \) | head -60
```
returned only `/workspace/assets/golden_masks/mask_{1x1,0p5x1,1x0p5,0p5x0p5}.gds`
and PDK files under `/workspace/gf180mcu/...` — no `ws_ip` filename among them.

The brief's exhaustive grep, run over the whole image filesystem, finds the
string in exactly **two** real files — the script and the README — and nowhere
else (the `/proc` hits are the grep process's own command line):

```
$ docker run --rm --entrypoint bash ghcr.io/wafer-space/gf180mcu-precheck:latest \
    -c 'grep -rl "gf180mcu_ws_ip" / 2>/dev/null | head -50'
/workspace/scripts/klayout/generate_id.py
/workspace/README.md
/proc/1/task/1/cmdline
/proc/1/cmdline
/proc/7/task/7/cmdline
/proc/7/cmdline
```
(This command hit its 600s timeout — exit 124 — after emitting the above, so it
is not a certified-complete sweep of `/`. See "What I did NOT run".)

A targeted grep over the whole repo content agrees, adding only the PCell
library's registration of the *content* generator `gf180mcu_ws_pcells` (a
different string) — i.e. the name appears only as a *reference*, never as a
shipped cell:

```
$ grep -rn "generate_id\|ws_ip\|ws_pcells\|--cob\|template" /workspace \
    --include=*.py --include=*.sh --include=*.md --include=*.yml --include=*.yaml \
    --include=*.toml --include=*.json --exclude-dir=gf180mcu
```
(full hit list: `pcell_library/__init__.py:21,35`, `generate_id.py:15,18,35,50-71,109,206,215`,
`precheck.py:270,276,634`, `README.md:10,11,67,70`.)

**2. PDK trees — ABSENT, in both trees available here.**
The brief's path `/foss/pdks/` does **not exist on this host** — it is a path
*inside* the EDA container, not on the machine:
```
$ ls /foss/pdks
ls: cannot access '/foss/pdks': No such file or directory
```
So I discharged the check inside both PDK trees that actually exist:

- precheck image's own `PDK_ROOT=/workspace/gf180mcu` (variants A/B/C/D present):
  `grep -ril "ws_ip" /workspace/gf180mcu` -> no hits;
  `find /workspace/gf180mcu -iname "*ws_ip*"` -> no hits.
- `ghcr.io/vibeic/vibeic-eda:0.2.88`, which does have `/foss/pdks`
  (`asap7 ciel gf180mcuD ihp-sg13cmos5l ihp-sg13g2 nangate45 sky130A`):
  `find /foss/pdks -iname "*ws_ip*"` -> no hits.

This is the expected result and it confirms the brief's reading of the naming:
`ws` is **wafer.space**, the shuttle operator — not `fd` (foundry) or `ef`
(efabless). These are operator IP and will never appear in a PDK.

**3. Their public repos — FOUND.** `github.com/wafer-space/gf180mcu-project-template`,
cloned and measured as above. Quoted sentences: `librelane/macros/macros_5v.yaml:2`
"`# required: will be replaced with actual content`" and `src/chip_top.sv:264`
"`// Do not remove, necessary for tapeout`". The template's own README points
back at the precheck, closing the loop:
> `README.md:134-136` — "## Precheck / To check whether your design is suitable
> for manufacturing, run the [gf180mcu-precheck](https://github.com/wafer-space/gf180mcu-precheck)
> with your layout."

**4. efabless precedent — consistent, comparison only.** Same shape as caravel's
user-project-wrapper: the operator ships a template with the id cells pre-placed,
and the submitter fills the core. Not independently re-verified in this session —
I did not pull caravel; it is cited from the brief as background, not as evidence.

---

## What this means for Step 26.5ic

The step does not need a cell *generator*. It needs to **ingest the operator's
template** and preserve four fixtures through the flow:

1. Vendor / fetch `ip/gf180mcu_ws_ip__{qrcode_id,shuttle_id,project_id,marker}/`
   from the template repo (Apache-2.0, so vendoring is permitted with attribution).
   Pin the commit — the coordinates are pinned data and can move under us.
2. Register them as macros with GDS+LEF+LIB+vh and **the exact locations and
   orientations** in the table above. `shuttle_id` is `orientation: E`, not `N`.
3. Instantiate all four in chip_top with `(* keep *)` so synthesis cannot strip
   an empty, portless blackbox.
4. Leave the cells' *contents* alone. wafer.space overwrites them at submission
   via `--id`. Our job ends at the correctly-sized, correctly-placed placeholder.
5. The `marker` location depends on `$DIE_AREA` — it is die-size relative
   (`W-281, H-281`), so it must be recomputed per slot size, not hard-coded.

One honest caveat on scope: because all of this is gated behind `--cob`, it
blocks **CoB (chip-on-board) submissions only**. If a run targets the default
non-CoB packaging, precheck passes today without any of these cells. That makes
this a packaging-option-conditional requirement, not a universal one — worth
encoding as a condition on the step rather than an unconditional gate.

## What I did NOT run

- I did not run `precheck.py` itself, on any layout, in either mode. Every claim
  about its behaviour above is read from source, not observed from a run.
  In particular I did **not** empirically confirm the silent-no-op-when-not-CoB
  behaviour by feeding it a layout missing the cells; that is a code reading of
  the `if <cell>:` guards.
- I did not run `generate_id.py` to confirm the produced content actually matches
  the placeholder bboxes at runtime (the `assert`s at 120/185/195/241). I matched
  the template's *shipped* sizes against the script's *constants*, which is a
  static match, not a dynamic one.
- The exhaustive `grep -rl "gf180mcu_ws_ip" /` from step 1 of the brief was cut
  off by its 600s timeout (exit 124), so it is **not** a complete sweep of `/`.
  It did emit its hits before being cut off, and they are quoted in section 1
  above; but a cell hidden somewhere it had not yet reached would have been
  missed by that particular command. The exhaustive `find / -xdev` for layout
  files *did* run to completion and covers that gap for `.gds`/`.oas`/`.lef`.
- I did not verify the template against a *newer* precheck image than `:latest`
  as of this run, nor check whether the 1x1 slot assumptions hold for the other
  three slot sizes (`0p5x1`, `1x0p5`, `0p5x0p5`) — only the `marker` is visibly
  die-relative, but the qrcode/shuttle/project bottom-left trio being absolute
  at (26,26) is something I read for the default slot only.
- I did not pull caravel to re-verify the efabless precedent in item 4.

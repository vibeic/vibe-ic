# The shuttle operator's slot contract, ingested — the first real run of step 0.5ic

Status: measurement. Every number below came OUT of the operator's template through
`submission_template_ingest`, with the file it came from and that file's digest.
Nothing here is retyped from a brief, and nothing is vendored: the template stays
outside this repository and this record carries paths and hashes, not bytes.

NDA: the shuttle's PDK/foundry/node name is elided as `<PDK>` throughout, following
the convention this repo's earlier precheck study set. Cell names, slot names, layer
geometry and digests are kept, because they are the checkable content.

---

## 1. THE TEMPLATE

    source     https://github.com/wafer-space/<PDK>-project-template  (Apache-2.0)
    commit     0de7e394337a1f7f5303ac7a3681bf2481b58176
    on disk    $HOME/_ext/<PDK>-project-template   — OUTSIDE this repository

Reproduce exactly:

    git clone https://github.com/wafer-space/<PDK>-project-template.git \
        $HOME/_ext/<PDK>-project-template
    git -C $HOME/_ext/<PDK>-project-template checkout 0de7e394337a1f

    python3 programs/submission_template_ingest.py <project> \
        --template $HOME/_ext/<PDK>-project-template --slot slot_0p5x0p5
    python3 programs/submission_template_check.py <project> \
        --json reports/phase1/submission_template.json

The ingester NEVER fetches. The clone above is a separate, explicit act by a human or
an agent; the step takes a path that is already on disk, which is what makes its
result reproducible.

Scan: 78 files seen, 11 config files examined, 0 unparsable, truncated=False.

## 2. THE FOUR SLOTS, AS INGESTED

All four carry `FP_SIZING: absolute` and pin both rects absolutely. `DIE_AREA` and
`CORE_AREA` are `[llx, lly, urx, ury]` in µm.

| slot | DIE_AREA | die W×H | CORE_AREA | core W×H | pads |
|---|---|---|---|---|---|
| `slot_0p5x0p5` | `[0, 0, 1936, 2531]` | 1936 × 2531 | `[442, 442, 1494, 2089]` | 1052 × 1647 | 56 |
| `slot_0p5x1` | `[0, 0, 1936, 5122]` | 1936 × 5122 | `[442, 442, 1494, 4680]` | 1052 × 4238 | 72 |
| `slot_1x0p5` | `[0, 0, 3932, 2531]` | 3932 × 2531 | `[442, 442, 3490, 2089]` | 3048 × 1647 | 72 |
| `slot_1x1` | `[0, 0, 3932, 5122]` | 3932 × 5122 | `[442, 442, 3490, 4680]` | 3048 × 4238 | 74 |

### Provenance — the file each came from, and its digest

| slot | source file (relative to the template) | sha256 |
|---|---|---|
| `slot_0p5x0p5` | `librelane/slots/slot_0p5x0p5.yaml` | `683e070cbd1137c4f3673aaa0eee92de97e749c71a5c51f42e56d0185c1a5a69` |
| `slot_0p5x1` | `librelane/slots/slot_0p5x1.yaml` | `70000b18cb94f4eeb6cb39eb5ff4f7f538b4f9af1b9446e2371bfc77e2489907` |
| `slot_1x0p5` | `librelane/slots/slot_1x0p5.yaml` | `d4931400c3e0b73eb52fb8c9fcd8e5e38c3b9e45d489b058bfefb375da4fd917` |
| `slot_1x1` | `librelane/slots/slot_1x1.yaml` | `beeb65a950bf77d1cca242637393eb3c5981b23b4e59d57603df80e58387be63` |

The slot NAME is the file stem in every case — these files declare no name key, so
the record says `slot_name_source: "file stem"` rather than inventing one.

### The pad list is FOUR lists, one per die side

| slot | PAD_SOUTH | PAD_EAST | PAD_NORTH | PAD_WEST | total |
|---|---|---|---|---|---|
| `slot_0p5x0p5` | 11 | 17 | 11 | 17 | 56 |
| `slot_0p5x1` | 8 | 28 | 8 | 28 | 72 |
| `slot_1x0p5` | 24 | 12 | 24 | 12 | 72 |
| `slot_1x1` | 17 | 20 | 17 | 20 | 74 |

## 3. AGREEMENT WITH THE OPERATOR'S OWN SIZE ARITHMETIC

Both sides of this comparison are first-hand. The template side came through the
ingester (§2). The gate side was read out of the submission gate's own source:

    wafer-space/<PDK>-precheck   commit 8d58ff75fb9e2169a37876696eb470a42c6c9701
    scripts/klayout/check_size.py:8-16, :84-101

        USER_PROJECT_WIDTH  = 3880          SEAL_RING_SIZE     = 26
        USER_PROJECT_HEIGHT = 5070          SAW_STREET_MINIMUM = 60
        USER_DIE_WIDTH  = USER_PROJECT_WIDTH  + 2 * SEAL_RING_SIZE   = 3932
        USER_DIE_HEIGHT = USER_PROJECT_HEIGHT + 2 * SEAL_RING_SIZE   = 5122

        slot_width  = (USER_DIE_WIDTH  - (div_x - 1) * SAW_STREET_MINIMUM) / div_x
        slot_height = (USER_DIE_HEIGHT - (div_y - 1) * SAW_STREET_MINIMUM) / div_y

The divisor table was read from the gate's own branches, the formula evaluated, and
the result compared against what the template pins:

    precheck --slot        gate computes        template pins   verdict
    0p5x0p5                  1936 x 2531          1936 x 2531   AGREE
    0p5x1                    1936 x 5122          1936 x 5122   AGREE
    1x0p5                    3932 x 2531          3932 x 2531   AGREE
    1x1                      3932 x 5122          3932 x 5122   AGREE

**ALL FOUR AGREE. No disagreement was found, so nothing had to be reconciled.**

The saw street is independently visible in the template alone, without the gate: the
full die minus two half dies is exactly it, in both axes.

    width   3932 - 2*1936 = 60          height  5122 - 2*2531 = 60

### One prose/data mismatch INSIDE the operator's own file — not a geometry conflict

`librelane/slots/slot_1x1.yaml` comments its die as

    # 3880umx5070um including 26um
    # for the sealring on all sides
    DIE_AREA: [0, 0, 3932, 5122]

The word *including* is wrong for its own numbers: 3932 = 3880 + 2·26, so 3880×5070 is
the die EXCLUDING the ring and `DIE_AREA` adds it. The DATA is right and matches the
gate; only the sentence is loose. Recorded here because a reader who trusts the comment
over the numbers will size a die 52 µm too small in each dimension.

### The ring is NOT declared as data anywhere

The ingester recorded `ring: null` for all four slots, and that is correct: the 26 µm
appears only in that COMMENT. The consequence is concrete — the checker's
`RING_DISAGREES` rule cannot fire on this template, because there is no declared ring
for the die to disagree with. What IS checkable, and was checked, is that the core sits
inside the die with a margin that is symmetric and identical across all four slots:

    core margin, all four slots, all four sides:  442 µm

That 442 is the ring plus the pad ring; the template does not decompose it, so neither
does this record. An implied number is reported as implied.

## 4. THE DIE-IDENTIFICATION FIXTURES

The ingester recorded 10 layout fixtures — 5 hard macros × (GDS + LEF). It does
NOT classify which are required; the template's own source does, at
`src/chip_top.sv:264-270`:

    // Do not remove, necessary for tapeout
    (* keep *) <PDK>_ws_ip__qrcode_id  qrcode_id  ();
    (* keep *) <PDK>_ws_ip__shuttle_id shuttle_id ();
    (* keep *) <PDK>_ws_ip__project_id project_id ();
    (* keep *) <PDK>_ws_ip__marker     marker     ();

    // …logo - can be removed if desired
    (* keep *) <PDK>_ws_ip__logo       …_logo     ();

So it is FOUR required and a FIFTH that is optional by the operator's own statement.
All five are shipped as PRE-BUILT layout: the operator's generator PLACES these cells,
it does not create them, which is why they had to be fetched and could never have been
computed.

| cell (from the fixture's own records) | view | bytes | sha256 |
|---|---|---|---|
| `<PDK>_ws_ip__logo` | gds | 91850 | `98d0cbbac50f436a3965346a99a5a43f…` |
| `<PDK>_ws_ip__logo` | lef | 548 | `4db0d8852ae66bbf772ce78aeae2d688…` |
| `<PDK>_ws_ip__marker` | gds | 828 | `5621522f25558d6850c7355a28caa7c7…` |
| `<PDK>_ws_ip__marker` | lef | 617 | `91c4a6fc76af31627759dd3b9eabfd58…` |
| `<PDK>_ws_ip__project_id` | gds | 4960 | `31e1e27e0e4ba5f881933f3fd73eb2e3…` |
| `<PDK>_ws_ip__project_id` | lef | 552 | `3d5a4dbe141c9c6053c65de57a194fcd…` |
| `<PDK>_ws_ip__qrcode_id` | gds | 105856 | `41080172af7f444881dba5d7c9521042…` |
| `<PDK>_ws_ip__qrcode_id` | lef | 555 | `f8633c388a0c6dad0c5199a82aa7d6eb…` |
| `<PDK>_ws_ip__shuttle_id` | gds | 4960 | `6c112fbba8bf3b65f4a22fd5a51ef5bd…` |
| `<PDK>_ws_ip__shuttle_id` | lef | 552 | `d76d7f041157979e0a943dcdafea80df…` |

Cell names were read out of the containers themselves (GDS structure records, LEF
`MACRO` names) and the two views agree for every macro. `cells_unread_reason` is null
for all ten — nothing was skipped and reported as empty.

All are declared to the flow by `librelane/macros/macros_3v3.yaml`, which also names a
`.lib` and a `.v` per macro. **This record does not carry those two views** — see §6.

## 5. WHERE `spmslot` SHOULD LOOK

Pick a slot, then take its `DIE_AREA` and `CORE_AREA` verbatim from the table in §2.
The smallest purchasable die is `slot_0p5x0p5`, 1936 × 2531 µm.

**The two names for one slot are not the same string.** The template's slot FILE is
`slot_1x1.yaml`; the submission gate's flag is `--slot 1x1`, with no `slot_` prefix
(`check_size.py:84-96` accepts exactly `1x1`, `0p5x1`, `1x0p5`, `0p5x0p5` and exits -1
on anything else). Passing the file stem to the gate is an `Unsupported slot size`
exit; passing the wrong one of the four is worse, because the gate then compares the
die against a slot nobody bought and the run still looks like it ran.

The floorplan step consumes it as an OpenLane-style `config.json` under `input/`.
This exact handoff was PROVEN, not assumed — a config built from the ingested record
was read back by `programs/floorplan_contract.py`:

    input/config.json
    {
      "DIE_AREA":  [0, 0, 1936, 2531],
      "CORE_AREA": [442, 442, 1494, 2089],
      "FP_SIZING": "absolute"
    }

    floorplan_contract.extract_floorplan_contract(project) ->
        die_area_budget_um  = '1936x2531'
        constraints_present = True
        die_area_source     = 'input/config.json'


### Ready to paste — all four, so no number has to be re-derived

Each block is `input/config.json` for that slot. `--slot` is the flag the
submission gate takes; the filename it came from is beside it.

    # slot_0p5x0p5   (precheck: --slot 0p5x0p5   from librelane/slots/slot_0p5x0p5.yaml)
    {
      "DIE_AREA":  [0, 0, 1936, 2531],
      "CORE_AREA": [442, 442, 1494, 2089],
      "FP_SIZING": "absolute"
    }

    # slot_0p5x1   (precheck: --slot 0p5x1   from librelane/slots/slot_0p5x1.yaml)
    {
      "DIE_AREA":  [0, 0, 1936, 5122],
      "CORE_AREA": [442, 442, 1494, 4680],
      "FP_SIZING": "absolute"
    }

    # slot_1x0p5   (precheck: --slot 1x0p5   from librelane/slots/slot_1x0p5.yaml)
    {
      "DIE_AREA":  [0, 0, 3932, 2531],
      "CORE_AREA": [442, 442, 3490, 2089],
      "FP_SIZING": "absolute"
    }

    # slot_1x1   (precheck: --slot 1x1   from librelane/slots/slot_1x1.yaml)
    {
      "DIE_AREA":  [0, 0, 3932, 5122],
      "CORE_AREA": [442, 442, 3490, 4680],
      "FP_SIZING": "absolute"
    }

Two things this record gives that a hand-typed die does not, and both matter to a
submission:

  * the CORE_AREA. A design that sets `DIE_AREA` and lets the core auto-size will not
    leave the 442 µm the pad ring and seal ring need.
  * the pad lists. `PAD_SOUTH` / `PAD_EAST` / `PAD_NORTH` / `PAD_WEST` in the slot file
    are instance names in the operator's `chip_top`, in ring order. A padring built in
    a different order is a different chip.

The full record, including all four slots whichever one is declared, is at
`reports/phase1/submission_template.json` of the ingest project, and one
`input/submission_template/slots/<slot>.yaml` per slot beside it.

## 6. WHAT THE INGESTER COULD NOT READ — and what that cost

**It read the geometry on first contact.** 4 slots, 4 dies, 4 cores, 4 sizing modes,
10 fixtures, 0 unparsable files, no scan truncation. The gate's verdict on the first
run was a correct refusal — `SLOT_NOT_DECLARED`, because no slot had been chosen.

**It did NOT read the pad lists, and recorded `pads: null`.** The candidate key names
were singular (`pads`, `PAD_LIST`, `PAD_ORDER`); the template spells them PER DIE SIDE.
Nothing refused that, so *this slot has no pads* and *this program did not understand
this slot* were the same sentence — which is the exact defect class step 0.5ic exists
to remove. Fixed in the same change as this note:

  * pad keys are matched by PATTERN, and every match is recorded separately;
  * the list-valued keys the pattern did NOT claim are recorded beside them, so a
    template that spells its pads a third way is visible on the FIRST run;
  * a new refusal, `PAD_LIST_UNREAD`, fires when a slot declares no recognised pad list
    while the same file carries list keys the program did not claim.

On the real template after the fix: 56 / 72 / 72 / 74 pads across the four slots, and
`unmatched_list_keys` names only `VERILOG_DEFINES` — which is a list, and is not pads.

**Still not recorded, stated so it is not mistaken for absence:**

  * the `.lib` and `.v` views (5 each) that ship beside every macro. This step records
    LAYOUT containers (GDS / LEF / MAG / OASIS); the timing and behavioural views are
    declared by `librelane/macros/macros_3v3.yaml` and are not in this record. The
    fixture count 10 is 10 of the 20 files those five macros ship.
  * the seal-ring width, because the template states it in a comment and this program
    does not read a contract out of prose.


## 7. WHAT THIS STEP'S OUTPUT NOW DECIDES — added when the flow base moved

The two paths stopped being a step-level key nothing read and became a
`condition: files_exist:` the enforcer actually evaluates. The files THIS step
writes are what those conditions test, so its output is no longer a note. It is
the router:

    input/submission_template/slots/*.yaml     -> 15.5ic, 26.5ic, 37.5ic apply
    input/submission_template/NO_TEMPLATE.txt  -> 37.5ip applies

Measured on the flow: no step blocks on 0.5ic and no step takes a
`required_input` from it, so **this step FAILING does not stop either path from
being selected.** The file existing is the whole decision.

### The defect that created, and the fix

The ingester used to write `NO_TEMPLATE.txt` on BOTH absent paths — the one that
searched and declared, and the one where nobody looked. Measured against the
flow's own predicate, those two rows were identical:

    ingest outcome                        15.5ic  26.5ic  37.5ic  37.5ip   0.5ic
    A  nobody looked                      skip    skip    skip    APPLIES  FAIL
    C  searched, absent, declared         skip    skip    skip    APPLIES  N/A

A run nobody investigated selected a delivery path, exactly as one that had
looked and said so. The three states this step exists to keep apart survived in
the report and were collapsed back to two by the router.

`NO_TEMPLATE.txt` is now written ONLY for a DECLARED absence — searched, not
there, and a stated reason at or above the flow's own floor, tested with the
same predicate the gate uses so a file the producer writes can never be one the
judge would have refused. When no decision came out of the run the step still
says so out loud, in `input/submission_template/NO_DECLARATION.txt`, which no
condition tests and which therefore selects nothing.

    ingest outcome                        15.5ic  26.5ic  37.5ic  37.5ip   0.5ic
    A  nobody looked                      skip    skip    skip    skip     FAIL
    B  searched, absent, NOT declared     skip    skip    skip    skip     FAIL
    C  searched, absent, DECLARED         skip    skip    skip    APPLIES  N/A
    D  ingested (the real template)       APPLIES APPLIES APPLIES skip     PASS

The report names the consequence directly, in `path_selector`: which file this
run wrote as the discriminator, whether it was a declaration, and what it
selects. A run that decided nothing says `"file": null, "declared": false`.

The test that holds this reads the conditions OUT OF the flow rather than
restating them, so it reddens if either side moves — including if nothing routes
on these files any more, which would make every other assertion in it vacuous.

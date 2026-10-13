---
name: catalog-glue-author
description: When design_one_shot_runner.step_rtl_gen WAIVES rtl_gen and ip_catalog_query has emitted matches, this skill pulls the matched open-source IP RTL into the project's canonical phase2/stage1/rtl/ directory and authors only the integration wrapper / chip-top + OpenLane config glue from L1-L27 spec. Replaces full-from-scratch spec-to-rtl authoring for SoC-class designs where pre-validated open-source IPs exist in the catalog. Triggers automatically when phase2 WAIVES with `fallback_skill=catalog-glue-author`.
---

# catalog-glue-author — Plugin IP integrator path

## When this skill fires

When `design_one_shot_runner.step_rtl_gen` returns:
```
WAIVED rtl_gen — IC class registered but rtl_gen=null.
                 Recommended action: AI invokes skill `catalog-glue-author`.
IP catalog matches found (evidence — the recommended skill is the one named in
`Recommended action` above; ...):
  - cpu/serv v1.4.0 (ISC) confidence=0.5; matched: ...
  - cpu/picorv32 v1.0.0 (ISC) confidence=0.5; matched: ...
```

RB2-01 (#2063): a catalog match on its own does NOT hand the design to this
skill. The IC class registry's own `fallback_skill` stands unless the INPUT
docs name the matched IP as this design's reuse; when they do not, the WAIVE
names `spec-to-rtl` and the matches are printed as evidence only. The match
list a run acted on is in
`...extras.ip_catalog_declared_reuse` (which matches were declared reuse) beside
`extras.ip_catalog_matches` (everything the query returned).

Plus `phase2_one_shot.json.steps[name=rtl_gen].extras.ip_catalog_matches` carries the structured match list.

This is the **Plugin SoC class path** identified by the strict-blind pilot finding: complex IPs (CPUs, large SoCs) cannot be reverse-engineered from 9-document spec. Plugin INSTEAD selects pre-validated open-source IPs from the catalog and authors only the integration wrapper.

## What this skill does

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Read project/reports/orchestrator/phase2_one_shot.json     │
│     extract rtl_gen.extras.ip_catalog_matches                   │
│                                                                  │
│  2. Re-rank if needed; user may override which IPs to include   │
│                                                                  │
│  3. For each selected IP, invoke ip_catalog_pull.py:            │
│     - Locate local mirror OR git clone canonical_url@commit     │
│     - License compliance check (reject GPL/AGPL/SSPL)           │
│     - Copy listed rtl_files to project/phase2/stage1/rtl/      │
│     - Compute SHA256 of each pulled file                        │
│     - Append provenance.jsonl record                            │
│                                                                  │
│  4. Read input/docs/L3 + L8 to determine chip-top wrapper       │
│     port contract + sub-module instantiation pattern             │
│                                                                  │
│  5. AI-author the chip-top wrapper (typically 50-300 LOC):      │
│     - Module declaration matching L3 ports                       │
│     - Instantiations of pulled IPs                               │
│     - Memory-mapped register decoder if L4/L5 needed             │
│     - Wishbone / AXI / custom bus adapters per L8 spec          │
│     - Reset polarity + clock distribution per L3                 │
│                                                                  │
│  6. Update project/plugin_output/declaration.json:              │
│     "rtl_strategy": "catalog_lookup_plus_ai_glue",              │
│     "ip_catalog_used": [...full audit per pull...],             │
│     "ai_authored_files": ["my_chip_top.v", ...],                │
│     "license_compliance_audit": {                                │
│        "all_permissive": true,                                   │
│        "spdx_set": ["ISC", "Apache-2.0", ...]                   │
│     }                                                             │
│                                                                  │
│  7. Re-run phase2 downstream steps (reference_tb / yosys /     │
│     sdc_gen) to verify integration compiles + meets spec        │
└─────────────────────────────────────────────────────────────────┘
```

## Invocation (called by phase2 runner or AI orchestrator)

```bash
# Step 3 — pull IPs (one command,加 --dry-run 先看 what would be pulled)
python3 plugins/vibe-ic/programs/ip_catalog_pull.py <project>

# Step 5 — AI-author wrapper (no script — pure AI task; this skill IS the spec)
```

The pull script:
- Reads phase1/generated_docs/ for facts
- Queries ip-catalog/ for matches (re-runs query as audit)
- Pulls listed rtl_files to phase2/stage1/rtl/
- Rejects any non-permissive license at pull time
- Updates declaration.json with rich audit metadata
- Logs each pull to provenance.jsonl

## AI authoring contract (Step 5)

When AI authors the chip-top wrapper, it MUST:

1. Read ONLY:
   - `<project>/input/docs/L*.md` (the spec)
   - `<project>/phase2/stage1/rtl/` (the pulled IPs — to see their port interfaces)
   - The Plugin's catalog manifest for each pulled IP (for parameter defaults + integration_notes)

2. AI MUST NOT:
   - Read original reference repos (oracle path)
   - Look at any existing chip-top wrapper from the open-source repo
   - The integration_guide.md serves as documentation; AI is allowed to read it

3. AI MUST author files with explicit attribution comments:
   ```verilog
   // SPDX-License-Identifier: <user's choice>
   // Author: Vibe-IC Plugin catalog-glue-author skill
   //
   // This module is the integration wrapper. It instantiates the
   // following open-source IPs (license: see source repos):
   //   - serv          (ISC,    github.com/olofk/serv@1.4.0)
   //   - shared_sram_rf (Apache-2.0, github.com/olofk/subservient@0.2.2)
   //
   // The instantiations and port wiring below are AI-authored from
   // input/docs/L3 + L8 spec. Sub-module RTL is unmodified from
   // its open-source upstream and is governed by its respective
   // license.
   module <name_from_L1.product_name>(...);
       // ... AI-authored instantiations
   endmodule
   ```

4. After the authored glue exists, record every authored RTL/header basename
   through the existing source producer (repeat the option for each file):

   ```bash
   python3 plugins/vibe-ic/programs/ip_catalog_pull.py <project> \
     --authored-glue top_wrapper.v --authored-glue local_defs.svh
   ```

   The producer hashes the actual files, independently verifies the official
   IP pins and rejects undeclared staged files. It writes structured
   `SOURCE_MANIFEST.json.ai_authored_files`, the declaration's existing
   `ai_authored_files` name list, and provenance while preserving free choices.
   Do not hand-fill hashes or producer-owned declaration fields. Register glue
   before applying a `--local-derivative` record; its parent, exact patch and
   unchanged native challenge evidence remain separate admission obligations.
   `pulled_ip_files` remains populated by the ordinary pull producer.

5. AI MUST run `iverilog -g2012 -t null <project>/phase2/stage1/rtl/*.v` as final sanity check before declaring success.

### Synchronous reset at an external memory interface

Read the complete input's memory retention and sampling obligations before
choosing the external memory protocol. Synchronous internal reset alone does
not authorize a pending write at the first edge that samples reset. If the
input requires all memory contents to retain throughout reset assertion, the
chosen protocol must suppress writes at that first edge and throughout held
reset. A declaration cannot introduce a first-edge exception to that input.
If the input explicitly permits a preceding transaction to commit at that
edge, declare that boundary and test the permitted behavior separately.

Preserve the complete registered transaction: write-enable launch, address and
data must stay aligned. For a memory that consumes writes only at the declared
clock edge, an external reset admission qualifier over the registered launch
can satisfy whole-memory retention without asynchronously resetting core
state. Check the actual sampling rule and all reset-edge transactions before
using this design. A memory that writes on a write-enable transition or during
an active level needs its own protocol analysis; this guidance does not make
raw reset qualification safe for those interfaces. Follow any separately
specified asynchronous safety behavior and any required port-waveform rule.

Distinguish an unsampled port waveform from a consumed memory transaction.
When the input allows a clock-sampled protocol and does not require a constant
between-edge write-enable waveform, record that waveform change diagnostically
and compare actual memory contents, firmware results and cycle counts with the
unpulsed baseline. Keep address/data alignment and observed core-state checks;
a reset pulse wholly between sampling edges must not change the sampled
execution. Require an observed active injection point before crediting reset
retention, and check every memory byte through the first edge and held reset.

Preserve original controls and receipts. If an earlier test enforced an extra
port-waveform condition from a prior protocol choice, freeze it and author a
new, separately identified protocol test; retain its input-derived memory,
firmware and reset assertions and known-bad value controls. Declare required
free choices through `spec_declaration_emit.py --set`, preserve imported IP
pins, and attribute the authored-glue correction separately. Do not waive an
input retention failure or hand-edit producer provenance to admit a repair.

## SOURCE_MANIFEST.json — the keystone reused-IP artifact (mandatory)

`phase2/stage1/rtl/SOURCE_MANIFEST.json` is the **keystone** that turns on
every reused-IP pin-gate relaxation. `l9_rtl_pin_consistency_check.load_source_manifest()`
reads THIS file (NOT `declaration.json`); it returns a usable dict **only** when
the file exists **and** declares `reused_ip: true`. When it returns `None`, the
gate falls back to a strict exact-name pin comparison — so a catalog-glue chip-top
(which intentionally flattens struct buses, ties off unused interfaces, renames
or exposes wrapper outputs) hard-FAILs with `L9 <-> RTL top pin/direction mismatch`.
The relaxations #659 (struct-bus flatten / tie-off), #711 (renamed interface),
and #712 (wrapper-exposed output) are **dead code without this file**.

### Who writes it on each path

- **catalog-pull path** (`ip_catalog_pull.py` ran, ≥1 IP pulled): the pull script
  AUTO-EMITS the manifest at pull time (`generated_by:"ip_catalog_pull"`). No
  action needed.
- **pre-staged vendor RTL path** (`input/vendor_rtl/` populated, the pull never
  runs): as of #732 `design_one_shot_runner.step_rtl_gen` AUTO-EMITS a minimal
  keystone manifest `{reused_ip:true, ip_list:[…], rtl_strategy:"catalog_lookup_plus_ai_glue",
  generated_by:"phase2_runner_prestaged"}` the moment it WAIVES to this skill
  (it reports the path in `extras.source_manifest_emitted`). You do **not** need
  to author the keystone from scratch — it already exists when this skill fires.

### Recognized fields

```json
{
  "reused_ip": true,                              // KEYSTONE — gate ignores file unless true
  "ip_list": ["aes", "tlul", "prim", "..."],      // structural provenance
  "rtl_strategy": "catalog_lookup_plus_ai_glue",
  "generated_by": "phase2_runner_prestaged",      // or "ip_catalog_pull" / your name on hand-author
  "tie_offs": ["clk_edn_i", "edn_i", "edn_o"],    // L9 ifaces wired to const/internal (no chip_top pad)
  "flattened_buses": [                            // #659 — struct bus split into wire-level children
    {"l9": "tl", "rtl": ["tl_a_*", "tl_d_*"]}
  ],
  "flattened_outputs": [                          // #712 — wrapper-exposed split outputs
    {"l9": "alert", "rtl": ["alert_n_o", "alert_p_o"]}
  ],
  "renamed_interfaces": [                         // #711 — L9 illustrative name ≠ RTL name
    {"l9": ["o_sram_addr"], "rtl": ["o_sram_waddr", "o_sram_raddr"]}
  ]
}
```

> **`renamed_interfaces` also carry pad SIDES on a DIE (D2).** The pad-ring
> producer (step 15.5ic) and the step-2 pad budget read these pairs through
> `_l_doc_pad_placement.accepted_renames`, which keeps only a pair phase 2's
> `spec_conformance_check` would accept (every `l9` name an L9 port the
> implemented core lacks, every `rtl` name an implemented port L9 does not
> declare, same direction, same width where both are literal); a rejected pair
> is recorded under `renamed_interfaces_rejected` with its reasons and places
> nothing. An accepted pair whose `l9` name falls in a
> pad-placement GROUP row ("SRAM data bus") puts its `rtl` names on that row's
> side. So keep every pair inside ONE placement group, never a whole interface
> in one pair, and never mix widths or directions in one pair (each `rtl` name
> is checked against each `l9` name): `{l9:[o_sram_data], rtl:[o_sram_wdata]}`,
> `{l9:[o_sram_addr], rtl:[o_sram_waddr, o_sram_raddr]}`, ... A pair whose
> `l9` names sit in two groups puts its RTL ports on two edges and is refused
> (PORT_ON_TWO_SIDES); a group no accepted pair (and no implemented port)
> reaches is refused (PAD_GROUP_UNRESOLVED at 15.5ic, DOES_NOT_FIT at step 2,
> even when no RTL bit is left without a pad).

> **Pad sides for renamed ports — PROGRAM FIRST, then you, then the program
> again (D9).** The manifest emitter runs `programs/renamed_interface_derive.py`.
> It writes the side-granular pairs the design's own records decide (R1: a
> read/write split of a document port's atoms; R2: the sole remaining group
> side) under **`derived_pad_pairs`**, each carrying `derived_by`, `rule`
> (`R1`/`R2`), `side` and `evidence`, and it keeps ONLY the pairs
> `accept_renames` accepts (the D2 rule above). It **never writes
> `renamed_interfaces`**. `derived_pad_pairs` is read by the pad side alone
> (`_l_doc_pad_placement.declared_renames`, steps 2 and 15.5ic).
> `spec_conformance_check` and `l9_rtl_pin_consistency_check` read
> `renamed_interfaces` as a DECLARED RENAME, and an R2 pair is evidence of a
> side, not of a rename. Do not copy a derived pair into `renamed_interfaces`
> unless you are declaring that rename yourself. A copy you make is yours and
> stays, fields and all. Only entries of the shape an earlier version wrote there
> (stamped, with no top-level `rule`) are moved out, and the hand-off names them.
> Acceptance runs per rtl port. A port the rule rejects is listed in
> `renamed_interfaces_derivation.rejected` with its own reasons and stays
> unresolved; its siblings keep their side. Ports it cannot decide, and ports the
> document places only in part, are listed in
> `renamed_interfaces_derivation.unresolved` with their candidate sides and the
> reason. Every emit refreshes all three program keys. HARD RULES for this skill:
> 1. For every port in `renamed_interfaces_derivation.unresolved`, do ONE of:
>    - author a `renamed_interfaces` pair for it, when a document port really
>      is its counterpart; or
>    - report it as a finding, when it has none. That is the case whose reason
>      reads "no document port shares an identifier atom with it", or when the
>      document's placement simply does not place it. Report it as a document
>      placement gap, and do NOT invent a pair to silence it: an authored pair
>      also tells both phase-2 gates that the document port is delivered as
>      this one.
>    Returning with a listed port neither paired nor reported is a failed
>    hand-off.
> 2. One pair per placement GROUP: every `l9` name of a pair must fall in the
>    same pad-placement group row by the exact-atom rule, and the pair must
>    pass `accept_renames` (same direction; same width where both are literal).
>    A port whose only candidate pair is rejected for a WIDTH the document and
>    the RTL disagree on is not yours to pair around: report it, do not author a
>    pair that hides the disagreement.
> 3. Then run `python3 programs/renamed_interface_derive.py <project> --check`.
>    It checks what the pad side will read: your pairs under every rename key
>    (`renamed_interfaces`, `renamed_buses`, `interface_renames`) and the
>    derived ones. Sides are counted per BIT NET, one pad per bit, as 15.5ic
>    places them, so a bus the document splits across two sides is fine. rc 0
>    means every implemented bit net ends on EXACTLY ONE side. rc 1 names:
>    - each REFUSED pair (an `rtl` name the implemented top lacks, an `rtl`
>      name the document already places on another side, an `l9` name L9 lacks,
>      an `l9` name in no group row, names in two groups, or any
>      `accept_renames` reason);
>    - each net with no side (`nets_without_side`);
>    - each net on two sides (`nets_on_two_sides`).
>    rc 3 is NOT_MEASURED, with the reason: the check cannot know an extent.
>    That is a design document that could not be read, a placement token whose
>    bit range does not resolve from a declared parameter (`o_x[SW-1:2]`, SW
>    undeclared), or a port whose width neither its RTL header nor L9 states.
>    State the missing parameter or width in the design input to resolve rc 3.
>    An RTL width the header cannot state (`[DW/8-1:0]`) is counted at L9's
>    width, as 15.5ic does. A definite two-side placement remains rc 1 even
>    when an extent is unknown; correct the placement in the design document.
>    A port you reported under rule 1 keeps rc 1 until the document places it,
>    so say so in the hand-off.

> **`{l9, rtl}` schema (HARD doc-and-code contract, #775).** Every `{l9, rtl}`
> dict above is parsed by `l9_rtl_pin_consistency_check._manifest_name_set()`:
> for `flattened_buses` the `l9` value names the **L9 struct ROOT** the chip-top
> flattens (the RTL pads are claimed by name-prefix shape `root_*`); for
> `flattened_outputs` the `rtl` value names the **exact RTL pad names** the
> wrapper exposes for an output L9 lacks entirely (`#712`). `l9` / `rtl` may each
> be a bare string or a string list. (Before #775 this consumer ignored the
> `{l9, rtl}` keys and silently dropped them — a manifest authored exactly per
> this doc produced an EMPTY relaxation set and the chip-top pin gate hard-FAILed;
> the consumer now matches the documented schema.) **§4.05 no-leak:** only the
> names you declare reconcile — a genuinely missing/extra functional port still
> hard-FAILs.

### Do NOT declare a port you cannot drive (HARD)

`tie_offs` means "the chip-top wires this L9 interface to a constant or an
internal net **instead of** a pad". It does **not** mean "this port does not
exist". Vendor docs frequently describe a **newer / superset integration
wrapper** than the revision staged in `input/vendor_rtl/` — an outer top that
adds redundancy, integrity or scrambling interfaces the staged sources simply
do not contain. Listing those under `tie_offs` asserts the delivered IC has a
safety surface it does not have, and buys a PASS by lying. Never do it.

You largely do not have to. `l9_rtl_pin_consistency_check` already demotes the
honest version of that divergence to a disclosed advisory with no manifest
entry, via the **#781 config-variant reconciliation**. Read what it keys on,
because the boundary is the whole point:

* the ground truth is the **DECLARED port list of the reused-IP module(s) the
  glue files actually instantiate** — resolved from `SOURCE_MANIFEST.ip_list`
  plus the SystemVerilog instantiation grammar, never the whole RTL tree;
* an L9 pin that is **not a port of the instantiated IP** is config-gated —
  the doc described a fuller variant than was built. Advisory.
* a chip_top port that **is** a real port of the instantiated IP but which L9
  named differently or omitted is faithful passthrough. Advisory.
* an L9 pin that **IS** a declared port of the instantiated IP and is missing
  from chip_top means the wrapper genuinely DROPPED a real port — still a hard
  FAIL. So does a chip_top port sourced from no instantiated IP at all.

A design with no manifest, or whose `ip_list` resolves to nothing, gets **no
relaxation whatever** — the reconciliation cannot be reached by omission.

**Where the relaxation does NOT reach, today.** The comparison surface is the
instantiated `ip_list` modules, not every module in the tree. A pin provided
only by some staged module the glue does not instantiate is outside it and
still hard-FAILs. Whether to widen the surface to all tree ports is an OPEN
question (vibe-ic#345, salvage 2): widening removes a class of false FAIL and
simultaneously weakens the no-leak property this rule depends on, so it needs
a measurement, not an opinion. Until it is settled, reserve
`renamed_interfaces` for a signal the staged IP genuinely drives under a
different name, and say **why** in a `rationale` field next to the pairing.

### MERGE-preserving rule (HARD)

The auto-emit is **merge-preserving**: it only (re)asserts `reused_ip` / `ip_list`
/ `rtl_strategy` and `setdefault`s `generated_by`. Any `tie_offs` / `flattened_buses`
/ `flattened_outputs` / `renamed_interfaces` block you hand-author **survives
untouched**. So when the chip-top wires an interface that the structural detection
cannot prove is intentional (e.g. an undeclared rename), **append** the
appropriate relaxation block to the existing manifest — never overwrite the file
wholesale, and never drop `reused_ip: true`.

## Synthesis-safe parameters (`synth_safe_params`)

When the catalog manifest for a pulled IP declares a `synth_safe_params`
list, AI MUST apply each `param → synth_safe_value` **by default** on
every SYNTHESIS instantiation of that IP, overriding the manifest's
`interface.parameters[].default`. The canonical case is a simulation-only
`generate` block gated by a `sim` / `debug` parameter that uses PLI or
system tasks (`$value$plusargs`, `$fopen`, `$display`, `$readmemh`):
yosys cannot elaborate those tasks, so instantiating with the sim value
(e.g. `sim = 1`) aborts synthesis, while the synth-safe value (e.g.
`sim = 0`) synthesises cleanly and the functional oracle still passes.
Read each pulled IP's `manifest.yaml.synth_safe_params`; for SERV this
pins `.sim(1'b0)`. The reference TB / functional oracle may still drive
the sim value during simulation — only the synthesis instantiation is
pinned to the synth-safe value. Document the applied pins in
`declaration.json` (e.g. `synth_safe_params_applied`).

## SystemVerilog conversion is IN-RUNNER — do not pre-convert (#587)

When a pulled IP is assertion-macro SystemVerilog (the `prim_assert`
pattern: a header whose `` `ifdef VERILATOR / `elsif SYNTHESIS / `else ``
chain `` `include ``s a macros file, plus packages and `.svh` headers),
**stage the files as-is and let the runner convert them**. As of
v0.3.41 `design_one_shot_runner._phase2_sv_synth_fallback` does the full
recipe in-container:

- stages the FULL closure — `.sv` sources **plus** `.svh`/`.vh`/`.h`
  headers and `*_pkg.*` package files found under `rtl/`;
- passes `-I <workdir>` so `` `include `` resolves;
- converts with **`-DSYNTHESIS`** (so the `` `elsif SYNTHESIS `` arm
  takes the synthesisable dummy-macros header, never the sim-only
  `` `else `` arm) — the TB/sim path separately keeps `-DSIMULATION`;
- chains `sv2v_mixed_driver_fixup` over the converted Verilog before
  yosys reads it.

Do **NOT** hand-roll `sv2v -DSYNTHESIS -I . …` outside the runner and
delete the `.sv` from `rtl/` (the round-6 work-around). Stage every
source + header + package the IP ships and let `step_yosys_synth` drive
the conversion; that is the supported, tested path. If synth still fails
with `Module 'X' referenced … is not part of the design`, run
`staged_rtl_closure_preflight.py <rtl_dir>` (#586) — a parameter DEFAULT
likely selects an excluded variant.

## License compliance gate

`ip_catalog_pull.py` enforces:
- Reject GPL-2.0 / GPL-3.0 / AGPL / LGPL / SSPL / CC-BY-SA / CC-BY-NC
- Accept ISC / MIT / BSD-2/3 / Apache-2.0 / CC0 / Public-Domain / CERN-OHL-P/W

The pulled IPs' SPDX identifiers are aggregated in `declaration.json.license_compliance_audit.spdx_set`. If user's project has a license declared in `<project>/LICENSE`, AI MUST verify it's compatible (typically the most-restrictive of pulled IPs' licenses, e.g. Apache-2.0 if any Apache-2.0 IP is pulled).

## Failure modes

- **No catalog matches** → fall back to original `spec-to-rtl` skill (full AI authoring from spec)
- **All matches REJECTED at license check** → emit ERROR with rationale; user must remove that IP from catalog or accept license incompatibility
- **rtl_files missing in source mirror** → partial pull;AI authors stubs for missing modules + logs in declaration.json.open_items
- **AI-authored wrapper fails iverilog parse** → RTL repair/retry loop (retry up to 3 iterations)

## What this skill is NOT

- ❌ Not a way to REVERSE-engineer open-source IPs from spec(that's reverse_engineering;forbidden per strict-blind doctrine)
- ❌ Not a license launderer(GPL IPs are REJECTED, not "licensed away")
- ❌ Not a magic "any spec → any RTL" generator(only works when catalog has a match)
- ❌ Not a substitute for human RTL designer expertise on novel architectures(those need new catalog entries first)

## Related artifacts

- Catalog: `plugins/vibe-ic/ip-catalog/<category>/<ip>/manifest.yaml`
- Schema: `plugins/vibe-ic/ip-catalog/_schema/ip_manifest.schema.json`
- Query engine: `plugins/vibe-ic/programs/ip_catalog_query.py`
- Pull engine: `plugins/vibe-ic/programs/ip_catalog_pull.py`
- Design doc: `plugins/vibe-ic/ip-catalog/CATALOG_INTEGRATION_DESIGN.md`
- Strict-blind motivation: `3rd_benchmark_strict_blind/STRICT_BLIND_CROSS_PILOT_REPORT.md`

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/catalog-glue-author/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

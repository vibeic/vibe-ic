---
name: catalog-glue-author
description: When phase2_one_shot_runner.step_rtl_gen WAIVES rtl_gen and ip_catalog_query has emitted matches, this skill pulls the matched open-source IP RTL into the project's canonical phase2/stage1/rtl/ directory and authors only the integration wrapper / chip-top + OpenLane config glue from L1-L23 spec. Replaces full-from-scratch spec-to-rtl authoring for SoC-class designs where pre-validated open-source IPs exist in the catalog. Triggers automatically when phase2 WAIVES with `fallback_skill=catalog-glue-author`.
---

# catalog-glue-author — Plugin IP integrator path

## When this skill fires

When `phase2_one_shot_runner.step_rtl_gen` returns:
```
WAIVED rtl_gen — IC class registered but rtl_gen=null.
                 Recommended action: AI invokes skill `catalog-glue-author`.
IP catalog matches found (use catalog-glue-author skill...):
  - cpu/serv v1.4.0 (ISC) confidence=0.5; matched: ...
  - cpu/picorv32 v1.0.0 (ISC) confidence=0.5; matched: ...
```

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

4. AI MUST update `<project>/plugin_output/declaration.json` to list:
   - `ai_authored_files`: every .v file AI created (not the pulled IPs)
   - `pulled_ip_files`: every .v file the pull script copied (already populated by ip_catalog_pull.py)

5. AI MUST run `iverilog -g2012 -t null <project>/phase2/stage1/rtl/*.v` as final sanity check before declaring success.

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
v0.3.41 `phase2_one_shot_runner._phase2_sv_synth_fallback` does the full
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
- **AI-authored wrapper fails iverilog parse** → ECO loop (retry up to 3 iterations)

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

# IP Catalog Integration with Plugin Pipeline — Design Document

> How Plugin's Phase 2 / spec-to-rtl / phase3 flow should consume the IP catalog. Mid-fidelity design — implementation pending.

## Motivation

Strict-blind pilot proved Plugin can't reverse-engineer 2-3 kGE CPU from 9-document spec. Industry practice (= our path forward) is **catalog selection + glue authoring**, not RTL reinvention.

## Integration touch points (where the Plugin needs to change)

### Touch point 1:Phase 2 `detect_ic_class` extension

When `ic_class_profile.detect_ic_class()` returns one of the registered classes(`digital_arithmetic_primitive`, `digital_cmd_driven`, ...), ALSO scan IP catalog manifests for matches against L1-L27 facts.

Pseudo-code:
```python
def detect_ic_class_with_catalog(project):
    profile = detect_ic_class(project)  # existing
    facts = load_facts(project)         # from phase1/generated_docs

    catalog_matches = []
    for manifest_yaml in glob("ip-catalog/*/*/manifest.yaml"):
        ip = load_yaml(manifest_yaml)
        for pattern in ip.get("matches_when", []):
            if evaluate_pattern(pattern, facts):
                catalog_matches.append({
                    "ip_name": ip["ip_name"],
                    "category": parent_dir_of(manifest_yaml),
                    "version": ip["ip_version"],
                    "license": ip["license"],
                    "manifest_path": manifest_yaml,
                    "matched_pattern": pattern,
                })

    profile["ip_catalog_matches"] = catalog_matches
    return profile
```

### Touch point 2:`design_one_shot_runner.step_rtl_gen` enhancement

When deterministic `rtl_gen` returns null AND catalog has matches, Plugin emits:
```
WAIVED   rtl_gen        IC class 'digital_arithmetic_primitive' has rtl_gen=null.
                        Catalog matches found:
                          - cpu/serv (matched 'L2.cpu_arch contains bit-serial')
                          - memory/shared_sram_rf (matched 'L2.memory_topology == unified')
                        Recommended action:
                          AI invokes catalog-glue-author skill — pull serv +
                          shared_sram_rf RTL into phase2/stage1/rtl/, author
                          chip-top wrapper from L8 spec.
```

### Touch point 3:New `catalog-glue-author` skill

A Plugin skill that:
1. Reads `<project>/phase1/generated_docs/L*.json`
2. Reads `<project>/reports/orchestrator/phase2_one_shot.json` for catalog matches
3. For each matched IP:
   - `git clone` or `wget` the canonical URL at pinned commit to `<project>/phase2/stage1/rtl/_catalog_ip/<ip_name>/`
   - Verify license SPDX matches expected
   - Copy listed rtl_files into `<project>/phase2/stage1/rtl/`
4. AI authors chip-top wrapper that:
   - Instantiates matched IPs (per L8 spec)
   - Wires up ports per L3 spec
   - Adds peripheral controllers per L8 spec
5. Updates `<project>/plugin_output/declaration.json`:
   ```json
   {
     "rtl_strategy": "catalog_lookup_plus_ai_glue",
     "ip_catalog_used": [
       {
         "ip": "serv",
         "category": "cpu",
         "version": "1.4.0",
         "license": "ISC",
         "canonical_url": "github.com/olofk/serv",
         "commit_pinned": "<sha>",
         "spec_match_pattern": "L2.cpu_arch contains 'bit-serial'",
         "rtl_files_pulled": [...]
       },
       {
         "ip": "shared_sram_rf",
         "license": "Apache-2.0",
         ...
       }
     ],
     "ai_authored_files": [
       "subservient.v",           // SoC top wrapper
       "gpio_periph.v"            // Wishbone GPIO peripheral
     ],
     "license_compliance_audit": {
       "all_permissive": true,
       "spdx_set": ["ISC", "Apache-2.0"]
     }
   }
   ```
6. License compliance check:reject if any matched IP has GPL/AGPL/SSPL (would taint user design).

### Touch point 4:`phase23_completion_audit` extension

Include IP catalog audit in the final summary:
```
=== Final Audit ===
✅ Plugin pipeline complete.
   Phase 1: 14/14 L docs, 100% coverage
   Phase 2: classifier=riscv_soc, IP catalog matched 2 IPs
   Phase 3:  synth + PnR + GDS + DRC PASS
   IP catalog usage:
     - cpu/serv@1.4.0 (ISC) — 18 files pulled
     - memory/shared_sram_rf@0.2.2 (Apache-2.0) — 6 files pulled
   AI-authored: 2 files (240 LOC chip-top wrapper)
   License compliance: ✅ all permissive (ISC + Apache-2.0)
```

## Schema invariants Plugin must enforce

1. **Permissive license only** — reject GPL/AGPL/SSPL at manifest load
2. **Commit pinning** — `canonical_commit` MUST be a SHA / version tag (not "HEAD" / "master") for reproducibility
3. **License attribution in GDS** — include IP name + license + commit in GDS comments / stream metadata
4. **No GPL-taint propagation** — if user's project includes a GPL IP, Plugin refuses to bundle

## Quality gates for adding new IPs to catalog

Each catalog IP must:
- Have OpenLane CI badge or documented tape-out track record
- Have iverilog/verilator/yosys-compatible RTL
- Pass `ip_catalog_validate.py` schema check
- Have integration_guide.md with at least 1 typical wiring example
- Have synth.area_ge measured / estimated under sky130 or gf180mcu

## Roll-out path

### Phase 1 (this commit): Catalog scaffolding
- ✅ Directory structure created
- ✅ Schema document
- ✅ 5 example manifests (SERV, sha256_core, PicoRV32, Ibex, shared_sram_rf)
- ✅ Integration design document

### Phase 2 (next iteration): Plugin runtime hookup
- Add `_query_catalog(facts)` helper in `ic_class_profile.py`
- Extend `design_one_shot_runner.step_rtl_gen` to emit catalog matches in WAIVED detail
- Add `catalog-glue-author` skill (Markdown + YAML)
- Add `ip_catalog_validate.py` script
- Add `declaration.json.ip_catalog_used` field documentation
- Unit tests: 5 IPs × 3 spec match scenarios each = 15 test cases

### Phase 3 (future): Auto-pull + license enforcement
- Auto-clone canonical repos at pinned commit
- SPDX license header scan
- GDS metadata injection
- AppSec scan (CVE check for known crypto vulns)
- Catalog browser UI (web)

## Provenance + Audit

Every catalog IP usage is recorded in:
1. `<project>/plugin_output/declaration.json` (rich JSON)
2. `<project>/provenance.jsonl` (append-only log, 1 line per IP pull)
3. `<project>/phase3/stage4/foundry_handoff/ip_catalog_audit.json` (foundry deliverable)
4. GDS user-data record (commit hashes embedded in chip metadata)

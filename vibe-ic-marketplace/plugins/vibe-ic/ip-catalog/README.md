# Vibe-IC IP Catalog

> Open-source IP registry that lets Plugin select pre-validated open-source IP blocks instead of reinventing them from spec. **Addresses strict-blind pilot finding that Plugin cannot reverse-engineer complex IPs (CPUs, large SoCs) from 9-document spec alone.**

## Why this exists

Strict-blind pilots(`3rd_benchmark_strict_blind/`)revealed a fundamental boundary:

| IC class | docs → RTL strict-blind | Plugin真實 capability |
|---|---|---|
| Textbook-algorithm primitive(`spm` carry-save multiplier) | ✅ 101 LOC AI-authored, 205/205 functional vs oracle | Plugin can author from textbook |
| Public-standard crypto(`sha256` NIST FIPS-180-4) | ✅ 483 LOC AI-authored, 3 NIST test vectors PASS | Plugin can author from standard |
| **Complex SoC + CPU**(`subservient` SERV-based RV32I)| ❌ 319 LOC structural stub, **RV32I semantics OPEN** | **Plugin cannot reverse-engineer 2-3 kGE CPU** from 9-document spec |

For the third class, the right industry practice is **IP catalog selection + integration glue**(not RTL reinvention). This catalog enables Plugin to act as **IP integrator** when spec mandates a known open-source IP architecture(`bit-serial RV32I`, `NIST SHA-256`, `Wishbone interconnect`, etc.).

## How Plugin uses this catalog

1. **Phase 2 classifier** identifies IC class(`riscv_soc`, `crypto_hash`, ...)
2. **spec-to-rtl AI fallback** queries catalog by spec markers before authoring:
   - L2 says "bit-serial RV32I" → matches `cpu/serv/` manifest
   - L2 says "NIST SHA-256" → matches `crypto/sha256_core/` manifest
   - L2 says "Wishbone XBar" → matches `interconnect/wishbone_xbar/`
3. **Plugin output declaration.json** records IP selections:
   ```json
   {
     "rtl_strategy": "catalog_lookup_plus_ai_glue",
     "ip_catalog_used": [
       {"ip": "serv", "version": "1.4.0", "license": "ISC", "commit_pinned": "..."},
       {"ip": "subservient_core", "version": "0.2.2", "license": "Apache-2.0", "commit_pinned": "..."}
     ],
     "ai_authored_files": ["my_chip_top.v", "my_chip_gpio.v"]
   }
   ```
4. Plugin still **authors the integration wrapper**(L8-driven module instantiation + L3-driven port routing) and **the OpenLane config**(L1-derived PDK target + L9 SDC)

## Catalog organization

```
ip-catalog/
├── _schema/
│   └── ip_manifest.schema.json    ← JSON Schema validation
├── cpu/                            ← Soft cores (RV32I/SPARC/ARM-free etc.)
│   ├── serv/                       ← Olof Kindgren's bit-serial RV32I (ISC)
│   ├── picorv32/                   ← Clifford Wolf's RV32IMC (ISC)
│   └── ibex/                       ← lowRISC RV32IMC (Apache-2.0)
├── crypto/                         ← Crypto primitives
│   ├── sha256_core/                ← secworks NIST SHA-256 (ISC)
│   ├── chacha/                     ← secworks ChaCha20 (ISC)
│   └── aes_core/                   ← secworks AES (ISC)
├── memory/                         ← Memory subsystems
│   └── shared_sram_rf/             ← SERV's shared SRAM for I-mem+D-mem+RF (Apache-2.0)
├── peripheral/                     ← I/O blocks
│   ├── gpio/                       ← Wishbone GPIO (various licenses)
│   ├── uart/                       ← UART16550-style (BSD)
│   └── timer/                      ← Standard timer (various)
└── interconnect/
    ├── wishbone_xbar/
    └── wb_intercon/
```

## License compliance

ALL IPs in this catalog MUST be one of:
- ISC / MIT / BSD-2-Clause / BSD-3-Clause(permissive,linker-compatible)
- Apache-2.0(permissive + patent grant)
- CC0 / Public Domain
- CERN-OHL-P / CERN-OHL-W(open-hardware license)

NO GPL / AGPL / SSPL IPs(would force user designs to be open-source — incompatible with chipIgnite shuttle commercial use).

Plugin's catalog selector enforces this at lookup time and includes license in declaration.json for audit trail.

## How to add a new IP

1. Choose category dir(create new one if needed)
2. Create `<ip_name>/manifest.yaml` per `_schema/ip_manifest.schema.json`
3. Write `<ip_name>/integration_guide.md`(human-readable how-to-wrap)
4. Run `python3 ip_catalog_validate.py <ip_name>/manifest.yaml`
5. Submit PR

See `cpu/serv/` for a complete reference example.

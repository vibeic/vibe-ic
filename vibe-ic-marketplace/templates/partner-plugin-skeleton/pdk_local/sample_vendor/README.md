# Sample Vendor PDK

Drop your PDK files under this directory. Phase 3 runner auto-detects:

- `liberty/*.lib` — at least one corner (typ preferred)
- `lef/{tech.lef,cell.lef}` — tech LEF + cell LEF
- `gds/*.gds` — std-cell GDS (optional, for GDS merge)
- `drc/*.{lydrc,rule}` — DRC deck (KLayout / Calibre)
- `lvs/*.{rule,device}` — LVS deck

After populating, append an entry to `plugins/vibe-ic/programs/pdk_registry.json` documenting your PDK conventions (site name, metal prefix, clock buffer cell, DRC deck path).

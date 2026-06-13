# Contributing — NEW_PDK

This is a focused per-topic guide. For the umbrella partner-plugin layout
+ submission workflow, see [`CONTRIBUTING_PARTNER_PLUGIN.md`](./CONTRIBUTING_PARTNER_PLUGIN.md).

## What you ship

Place under `pdk_local/<vendor>/<process>/` in your partner plugin:

```
pdk_local/<vendor>/<process>/
  liberty/
    *.lib                     ≥1 corner (tt preferred default)
  lef/
    {tech.lef, cell.lef, *.lef}
  gds/*.gds                   std-cell GDS
  drc/*.{lydrc, drc, rule}    KLayout / Calibre / Magic decks
  lvs/*.{rule, device}        LVS decks
  README.md                   site name, metal prefix, clk buf cell
```

## Register the PDK

Append to `plugins/vibe-ic/programs/pdk_registry.json`:

```json
{
  "name": "<vendor>_<process>",
  "process_node_nm": <int>,
  "open_source": <bool>,
  "container_path": "/foss/pdks/<name>",
  "liberty_glob": "<relative path>",
  "tech_lef_glob": "<relative path>",
  "cell_lef_glob": "<relative path>",
  "site": "<SITE name from cell LEF>",
  "metal_prefix": "<met / Metal / MET>",
  "clk_buf_cell": "<low-drive clock buffer>",
  "clk_buf_root_cell": "<high-drive clock buffer>",
  "drc_deck": "<.lydrc path>",
  "lvs_deck": "<.tcl path>",
  "owner_plugin": "partner-<vendor>-<process>"
}
```

`phase3_one_shot_runner` consults this registry; auto-detection from the LEF still works as fallback when no entry matches.

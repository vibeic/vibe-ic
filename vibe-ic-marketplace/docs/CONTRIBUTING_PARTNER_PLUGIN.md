# Contributing a Partner Plugin to Vibe-IC Marketplace

Vibe-IC is an open platform. Vendors, foundries, IP suppliers, EDA-tool
authors, and the community can ship their own plugins as **siblings**
of the reference `vibe-ic` plugin in this marketplace — no fork
required, no core changes required.

This guide covers the four common contribution shapes:

1. **New IC class** (e.g. RFIC, MCU, sensor) — generator + reference TB
2. **New PDK / foundry** (e.g. commercial_foundry commercial_pdk, TSMC 65) — registry + sign-off decks
3. **New device / tester / scope** (e.g. ACME-9000 tester) — driver + manifest
4. **New methodology / skill** (e.g. specialised analog flow) — SKILL.md + agents

---

## 0. Plugin layout

```
plugins/
  partner-<vendor>-<topic>/
    .claude-plugin/
      plugin.json
    commands/                       (optional slash commands)
    skills/                         (optional NL skills)
    agents/                         (optional sub-agents)
    programs/                       (optional deterministic Python)
    mcp-eda/ + .mcp.json     (optional vendor MCP tools)
    pdk_local/<vendor>/             (optional PDK + IP macros)
    devices/<class>/<vendor>/       (optional device drivers)
    README.md
    CHANGELOG.md
```

Naming: `partner-<vendor>-<topic>` (lowercase). Examples:
- `partner-commercial_foundry-commercial_pdk`
- `partner-memvendor-otp128x8`
- `partner-tsmc-65nm`
- `partner-acme-tester-md9000`
- `community-class-rfic`

---

## 1. Add a new IC class

Implement at minimum:

| File | Role |
|---|---|
| `programs/<class>_rtl_gen.py` | Deterministic RTL generator (chip-AGNOSTIC within the class) |
| `tools/protocol_tb/<class>_reference_tb.v` | Reference TB used by the Phase 2 runner |
| `programs/<class>_class_profile.py` | Detection + applicability rules |
| `skills/<class>-spec-extract/SKILL.md` | NL fallback for unfamiliar variants |

Register the class in `programs/ic_class_registry.json` (planned shared
registry — until then, append a row in your plugin's
`docs/CLASS_REGISTRY.md` so users know).

---

## 2. Add a new PDK

Place under `pdk_local/<vendor>/<process>/`:

```
pdk_local/<vendor>/<process>/
  liberty/*.lib                     (≥1 corner; tt preferred default)
  lef/{tech.lef,cell.lef,*.lef}
  gds/*.gds                         (std cell)
  drc/*.{lydrc,drc,rule}            (KLayout / SVRF / Calibre)
  lvs/*.{lyrdb,rule,device}
  README.md                         (site, metal-prefix, clk-buf-cell)
```

`phase3_one_shot_runner.py` auto-detects PDK from the project's
`input/pdk/` first; vendor partner plugins ship a sample under
`templates/<class>-with-<vendor>/input/pdk/` that copies these files into
new projects.

---

## 3. Add a new device / tester / scope

```
mcp-eda/src/devices/<class>/<vendor>/
  driver.py                         (or driver.js / driver.go — exec'd by MCP server)
  manifest.json                     (name, schema, modes, permissions)
  README.md
```

`manifest.json` schema mirrors the existing
`mcp-eda/src/devices/tester/vendor-usb_hid_tester/manifest.json` and
`mcp-eda/src/devices/fpga/terasic-de10lite/manifest.json`.
Plugin's `.mcp.json` lists the additional MCP servers if you ship more
than just driver wrappers.

---

## 4. Add a new skill

```
skills/<vendor>-<topic>/SKILL.md
```

Frontmatter format follows `vibe-ic/skills/phase1/SKILL.md`. Skills
trigger when their description matches user intent; AI invokes them when
no deterministic runner covers the case.

---

## Submission

1. Fork the marketplace repo (or open a PR adding your plugin under
   `plugins/partner-<vendor>-<topic>/`).
2. Add a row to root `marketplace.json#plugins[]`.
3. Run `python3 plugins/vibe-ic/programs/marketplace_version_sync_check.py
   --marketplace-dir <repo-root>` to verify version sync.
4. Send PR. Maintainers review for chip-AGNOSTIC compliance: your
   programs/skills/tools must NOT hardcode another vendor's product names
   in core logic (vendor names in your own plugin's code is fine).

---

## Key rules

1. **Do not modify `plugins/vibe-ic/`** — open issues / PRs against
   reference plugin only when your contribution generalises the core
   for everyone. Vendor specifics live in your sibling plugin.
2. **Match the marketplace contract** — your plugin must run cleanly
   when installed alongside the reference plugin (no path collisions,
   no command-name collisions).
3. **chip-AGNOSTIC where it can be** — your IC class plugin should not
   embed assumptions about another class's chips.
4. **Provide a small reference project** under
   `templates/<your-plugin-name>-example/` so users can `/vibe-ic-all`
   it and confirm your plugin works.

# Partner Plugin Skeleton

Copy this directory into `vibe-ic-marketplace/plugins/partner-<your-vendor>-<topic>/`,
edit the placeholders, register in root `marketplace.json`, and submit a PR.

## Layout

```
partner-<vendor>-<topic>/
├── .claude-plugin/
│   └── plugin.json                 (name, version, description, author)
├── commands/                       (optional slash commands — extend /vibe-ic-*)
│   └── <your-command>.md
├── skills/                         (optional NL skills)
│   └── <your-skill>/SKILL.md
├── programs/                       (optional deterministic Python — generators / gates)
│   └── <your-class>_rtl_gen.py
├── mcp-eda/                 (optional — only if shipping new MCP tools)
│   └── src/devices/<class>/<vendor>/
│       ├── manifest.json
│       └── driver.py
├── pdk_local/<vendor>/             (optional — PDK + IP macros)
│   └── liberty/, lef/, gds/, drc/, lvs/
└── README.md
```

## What to register where

| You add | Register in |
|---|---|
| New IC class generator | Append to `plugins/vibe-ic/programs/ic_class_registry.json` (PR) |
| New PDK | Append to `plugins/vibe-ic/programs/pdk_registry.json` (PR) |
| New device / tester / scope | Drop manifest under `mcp-eda/src/devices/<class>/<vendor>/`; auto-detected by `_registry.js` at MCP server start |
| New skill | Just put SKILL.md in `skills/<name>/`; Claude auto-loads when keywords match |
| New deterministic gate | Drop `<gate>_check.py` under `programs/`; reference in `flow/phase*.yaml` |
| New slash command | Drop `<name>.md` under `commands/` |

## Required first step

Before contributing, read:
- `docs/CONTRIBUTING_PARTNER_PLUGIN.md` (umbrella guide)

## Validate your plugin locally

```bash
cd vibe-ic-marketplace/
# Add your plugin to root marketplace.json's plugins[] array first.
python3 plugins/vibe-ic/programs/marketplace_version_sync_check.py \
    --marketplace-dir .
# If FAIL, fix the version field in your plugin.json.
```

## Test install locally

```bash
# Symlink your plugin into Claude Code cache:
ln -s $(pwd)/plugins/partner-yourname-topic \
      ~/.claude/plugins/cache/vibe-ic-marketplace/partner-yourname-topic/0.1.0
```

Then restart Claude Code and verify your slash commands / skills appear.

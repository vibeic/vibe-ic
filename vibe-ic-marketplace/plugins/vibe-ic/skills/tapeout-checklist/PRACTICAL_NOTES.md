# Tapeout Checklist — Practical Notes

**Added**: 2026-04-07 from a digital full-flow pilot review

## Realistic Tapeout Readiness Progression

From pilot experience (single session, ~6 hours):

| Milestone | Green Items | % | What it took |
|-----------|------------|---|-------------|
| Start (RTL only) | 11/38 | 29% | Cowork had generated RTL + docs |
| After synthesis + P&R | 15/38 | 39% | Install EDA tools, run Yosys+OpenROAD |
| After formal + STA | 25/41 | 61% | SymbiYosys 6 modules, 5-corner STA |
| **Digital-only tapeout ready** | ~30/41 | **73%** | Fix detailed routing + full formal |
| Full chip tapeout | 41/41 | 100% | Analog design + DFT + ESD (weeks) |

## Key Insight: 73% is Achievable with AI + Open-Source

The remaining 27% requires:
- Analog IC designer (LDO/POR/OSC)
- Commercial DFT tools (scan insertion)
- ESD cell integration

## Tiny Tapeout vs Full Tapeout

| Check | Tiny Tapeout | Full Tapeout |
|-------|-------------|-------------|
| DRC | ✅ Handled by TT infrastructure | Must be clean |
| LVS | ✅ Not required (digital macro) | Must match |
| Analog | ✅ Not needed (digital only) | Required |
| ESD | ✅ Provided by TT frame | Must design |
| DFT | ✅ Not needed (small area) | Required for yield |
| IO pads | ✅ Provided by TT | Must integrate |

**For prototype validation, Tiny Tapeout is the fastest path.**

## GF180 DRC Tips

- Use KLayout with official rule decks (not Magic)
- Path: `/foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py`
- Set `PATH` to include `/foss/tools/klayout` before running
- Use `--no_feol` for BEOL-only check if standard cells are trusted
- Variant C = 9K metal_top, 5LM (most common)

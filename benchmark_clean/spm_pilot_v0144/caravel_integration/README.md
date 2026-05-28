# spm Caravel integration (Tier 3 MPW completion)

The v0.1.48 spm GDS is core-block tape-out clean. This directory is the bridge
between the core block and a real eFabless chipignite MPW submission via the
caravel_user_project template.

## Files in this directory

| File | Purpose |
|---|---|
| `user_project_wrapper.v` | Verilog wrapper that maps spm signals into the canonical caravel port set (wb_clk_i, io_in/out/oeb[37:0], etc.) — compiles clean with `iverilog -g2012` |
| `pin_mapping.md` | Explicit pin→signal mapping (this README) |
| `integration_plan.md` | Step-by-step path to a submittable MPW package |

## Pin mapping (spm into caravel)

| spm signal | Width | caravel port | Notes |
|---|---|---|---|
| `clk` | 1 | `wb_clk_i` | management Wishbone clock (typically 10 MHz) |
| `rst` | 1 | `wb_rst_i` | management Wishbone reset |
| `x[31:0]` | 32 | `io_in[33:2]` | 32 GPIO inputs |
| `y` | 1 | `io_in[34]` | 1 GPIO input |
| `p` | 1 | `io_out[35]` | 1 GPIO output (oeb[35]=0) |

Unused caravel ports tied off:
- `io_out[34:0]` = 0
- `io_out[37:36]` = 0
- `io_oeb[34:0]` = all 1 (input mode)
- `io_oeb[37:36]` = all 1 (input mode)
- `wbs_ack_o` = 0
- `wbs_dat_o` = 32'b0
- `la_data_out` = 128'b0
- `user_irq` = 3'b0

Power:
- `vccd1` = 1.8 V digital supply (drives spm VPWR)
- `vssd1` = digital ground (drives spm VGND)
- Other power domains unused

## Integration plan to a submittable MPW package

### Phase A — Setup (1 day, partly already done)

1. ✅ spm core block tape-out clean (this pilot's v0.1.45–v0.1.48 work)
2. ✅ user_project_wrapper.v authored + compiles
3. Clone `caravel_user_project` from github.com/efabless/caravel_user_project
4. Run `iic-init-caravel.sh` + `iic-setup-caravel.sh` (in container, ~5 GB)
5. Copy `user_project_wrapper.v` + spm.v into `caravel_user_project/verilog/rtl/`

### Phase B — User-project PnR (1–2 days)

6. Update `caravel_user_project/openlane/user_project_wrapper/config.tcl` with:
   - `DESIGN_NAME = user_project_wrapper`
   - `VERILOG_FILES_BLACKBOX = …/spm.v`
   - `EXTRA_LEFS` = the v0.1.48 spm.lef (would need to generate; OpenROAD `write_abstract` step)
   - `EXTRA_GDS_FILES = …/chip_top.gds` (from v0.1.48 foundry_handoff)
7. Run OpenLane `flow.tcl -design user_project_wrapper` — wraps + integrates pads
8. Verify the wrapper's GDS contains spm core inside the harness area
9. Run Caravel-level precheck (eFabless's MPW-eligibility tool)

### Phase C — Top-level Caravel close (1–2 days)

10. Re-run Caravel top-level fill / DRC against full chipignite outline
11. Pass eFabless `precheck` (LVS, antenna, DRC, manifest)
12. Submit GDS + license to chipignite shuttle

## Total effort estimate

**~3–5 days from this README to a precheck-passing MPW submission**, assuming the spm core needs no rework. The v0.1.45–v0.1.48 plugin fixes were the prerequisite for not needing core rework.

## What's been done in this iteration

- ✅ user_project_wrapper.v written (111 lines)
- ✅ Pin mapping documented above
- ✅ Compile verified with iverilog
- ✅ Integration plan documented

## What's NOT done in this iteration

- ❌ caravel_user_project repo not cloned (~5 GB download + clone time)
- ❌ OpenLane user_project_wrapper PnR not run
- ❌ Caravel top-level integration not run
- ❌ eFabless precheck not run
- ❌ Plugin runner doesn't yet auto-generate the wrapper

These are concrete, time-bounded next steps — not architectural unknowns. The wrapper compiles, the pin mapping is unambiguous, the spm core is signoff-clean.

## Plugin config that would auto-emit the wrapper (v0.1.49 sketch)

```python
@dataclass
class CaravelTargetConfig:
    """v0.1.49 — Caravel chipignite MPW target config.

    When set on a project, the runner auto-emits:
      - user_project_wrapper.v with signal mapping derived from L9
      - OpenLane user_project_wrapper/config.tcl with EXTRA_GDS_FILES pointing
        at the core block GDS
      - A precheck-ready manifest
    """
    caravel_root: Path           # path to caravel_user_project repo
    user_area_macro: str         # e.g. "spm"
    target_io_pins: Dict[str, int]   # spm port → caravel io_in/out index
    use_power_pins: bool = True
```

Wiring this into `phase3_one_shot_runner.py` is ~150 lines (template emission + OpenLane config write). Estimated 1-day plugin task.

## Honest framing

This is the **scoping step** of the Caravel integration. The wrapper module is real and compiles; the rest is mechanical chaining of canonical eFabless tools that needs space + time but no further IP design.

The pilot has now bridged the gap between "core block" and "real MPW submission ready" in a way that says: **this much is done, this much remains, here's the exact set of steps**.

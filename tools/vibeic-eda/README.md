# vibeic-eda — forked + enhanced OSS EDA toolchain

`vibeic-eda` is the Vibe-IC EDA runtime: the [hpretl/iic-osic-tools] base (all
open-source EDA tools + sky130/gf180/ihp PDKs) with our **patched `vibeic/*`
forks** layered in to close capability gaps where stock open-source tools fall
short of commercial EDA. It replaces the plain `iic-osic-tools` (`iic-eda`)
container everywhere the plugin/MCP invokes EDA tools.

## Forks currently layered in

| Tool | Fork | Enhancement | Proof |
|---|---|---|---|
| OpenROAD | `vibeic/OpenROAD` (branch `vibeic/post-route-detailed-routing-repair`) | Post-detailed-route `repair_design`/`repair_timing` on **real** parasitics (OpenRCX/SPEF): exposes `estimate_parasitics -detailed_routing` and routes `kDetailedRouting` buffering through the placement-Steiner builder, fixing the Signal-11 crash + the silent wire-load fallback stock OpenROAD hits. | sky130 sha256 (routed, ss corner): stock **segfaults**; patched runs to completion and takes max-slew violators **289 → 0**, exit 0. |

Roadmap for the remaining forks (yosys/abc, klayout/magic, netgen, iverilog,
ngspice): `benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md` (P0–P6).

## Build

```bash
# reproducible, from source (builds the fork in the NATIVE ubuntu24.04 dev env so
# the binary matches the iic-osic-tools runtime — a 22.04 build wants libpython3.10)
docker build -t vibeic-eda:<ver> tools/vibeic-eda
```

The builder stage clones `vibeic/OpenROAD` at `OPENROAD_REF` (override with
`--build-arg OPENROAD_REF=...`), builds it, and the runtime stage copies the
patched `openroad` + its `/opt/or-tools` runtime over the iic-osic-tools base.

## Use

Run it exactly like `iic-osic-tools`; the patched `openroad` is at the same path
(`/foss/tools/openroad/bin/openroad`) so the Vibe-IC phase-3 flow uses it
transparently once the MCP/`iic-eda` container reference points at `vibeic-eda`.

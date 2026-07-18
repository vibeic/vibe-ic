# SOURCE_MANIFEST — caravel_user_project (`user_proj_example` macro), 0.2.20-int A/B

- **Upstream RTL:** https://github.com/chipfoundry/caravel_user_project (Apache-2.0), stock
  `user_proj_example` — a Wishbone/LA/GPIO-controllable up-counter (`counter` leaf). Reused
  verbatim (SPDX Apache-2.0 header intact); no RTL authored by us. Byte-identical to the 0.2.19
  baseline RTL (sha256 `af1666e0…`) so the A/B isolates the toolchain only.

- **Node under test:** a commercial 180 nm NDA PDK, staged at `input/pdk/` as symlinks to
  out-of-repo scratch. NDA content is **never** committed (see `.gitignore`).

- **Image:** `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (id `fa8cb832daf2`), throwaway container
  `vibeic-eda-int-caravel` (the running 0.2.19 `vibeic-eda` container was left untouched).
  Toolchain: OpenROAD `1cd84e502a`, Yosys `c31dfe3a8`, magic `8.3.675`, KLayout `0.30.9`.

- **A/B baseline:** `benchmark-data/ic/caravel_user_project/clean_run_v1432_commercial`
  (0.2.19, OpenROAD `5a00b6283a`), committed at `f43c65200`.

- **Scope (IC-specific constraint — HONEST):** only the **`user_proj_example` macro** is hardened
  on the commercial 180 nm node as a **standalone macro**. The full Caravel harness
  (`user_project_wrapper` padframe, management SoC, fixed die/pin/power template, sky130 hard-IP) is
  **sky130-bound by construction** with no commercial-180 nm equivalent — deliberately NOT attempted
  on the commercial node.

- **Shape:** A (full runner) for Phase 1/2 via `vibe_ic_one_shot_runner.py`, then
  `phase3_one_shot_runner.py --pdk custom:pdk --top-name user_proj_example --die-um 220x220 --util 0.3`
  for the real-node backend (synth → PnR → DRC → LVS → STA → IR). DRC = native SVRF interpreter on
  the foundry deck; LVS = KLayout-native + netgen.

- **Clean-room:** fresh run dir — no inherited results / memory / cache.

## NDA discipline (ABSOLUTE)

Results-only, NDA-EXCLUDED. This directory commits **metrics / verdicts only** (`.gitignore` +
`RESULT.md` + `SOURCE_MANIFEST.md`) — no PDK data, no device params, no foundry cell names, no SKU,
no rule-IDs, no deck paths. The staged `input/pdk/`, all layout binaries, tech-mapped netlists,
`*.rpt`/`*.log`, and the whole working/report trees are git-ignored so a careless dir-add can never
stage NDA-derived content. **Never** described as "silicon-proven".

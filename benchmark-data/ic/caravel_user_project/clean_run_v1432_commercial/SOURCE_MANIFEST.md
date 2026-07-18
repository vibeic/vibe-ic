# SOURCE_MANIFEST — caravel_user_project (user_proj_example macro) on a commercial 180nm PDK

- **Upstream RTL:** https://github.com/chipfoundry/caravel_user_project (Apache-2.0),
  stock `user_proj_example` — a Wishbone/LA/GPIO-controllable up-counter (`counter`
  leaf). Reused verbatim (SPDX Apache-2.0 header intact); no RTL authored by us.
- **Node under test:** a **commercial 180 nm NDA PDK**, staged at `input/pdk/` as
  symlinks to out-of-repo scratch. NDA content is **never** committed (see `.gitignore`).
- **Scope (IC-specific constraint — HONEST):** only the **`user_proj_example` macro**
  (the counter + Wishbone/LA/GPIO glue) is hardened on the commercial 180nm node as a
  **standalone macro**. The full Caravel harness — `user_project_wrapper` padframe,
  management SoC, fixed `DIE_AREA=2920x3520 µm`, fixed pin-order / power-pin `.loc`
  template, and the sky130 hard-IP — is **sky130-bound by construction** and has **NO
  commercial-180nm equivalent**. That portion is deliberately NOT attempted on the
  commercial node; doing so would be a fake result, not a tool failure. See `RESULT.md`
  §"sky130-bound by construction".
- **Shape:** A (full runner) for Phase 1/2 via `vibe_ic_one_shot_runner.py`, then
  `phase3_one_shot_runner.py` for the real-node backend (synth → PnR → DRC → LVS →
  STA) on `--pdk custom:pdk --top-name user_proj_example`.
- **Clean-room:** fresh run dir — no inherited RESULTS / memory / cache from the
  sky130 `clean_run_v1342`.

## NDA discipline (ABSOLUTE)
Results-only, NDA-EXCLUDED. This directory commits **metrics / verdicts only** — no
PDK data, no device params, no foundry cell names, no SKU, no rule-id. Layout binaries
(`*.gds *.lef *.lib *.def *.spef`), the staged `input/pdk/`, and tech-mapped netlists
are git-ignored. **Never** described as "silicon-proven".

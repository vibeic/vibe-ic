# vibeic-eda 0.2.22 — Image Delivery Manifest

> Reference for the NEXT image regen. Records every pinned fork ref, what changed this
> cycle, the new PDK + fork that were published for the first time, the NDA remediations,
> and the verification that gated the build. Written 2026-07-19.

**Image:** `vibeic-eda:0.2.22` · digest `sha256:8a493c221531e2506b293b8331cbec1f1ebe780bc1386422aaae58a1244d0ea0` · 26.9 GB · base `hpretl/iic-osic-tools:latest`
**Enhancement ledger at build:** done **305** / todo **0** / deferred 119 / external 58 (all 12 tools converged — every forkable item either fixed with an unfakeable gate, already-covered with a citation, or honestly classified).

---

## 1. Pinned fork refs (Dockerfile ARGs) — the source of truth for a regen

| Tool | REF | Branch | Changed this cycle? |
|---|---|---|---|
| **OpenROAD** | `1bade74e7224d9c631b13dec626d258af3f65196` | vibeic/openroad-integration | ✅ NEW consolidation |
| **yosys** | `330b3eb197398f5d9e568c72f364fd3c0efa6f82` | vibeic/synth-fixes-integration | ✅ NEW consolidation |
| **ngspice** | `6e9f78fb5dd56fa56c4d5599ca5c11717a4403ea` | vibeic/batch-honesty-integration | ✅ NEW consolidation + built `--enable-openmp` |
| **klayout** | `4e33e325ec167f03a293f3c4958bc9285131ad03` | vibeic/klayout-signoff-int | ✅ NEW (16 signoff ops) |
| **netgen** | `b711fa5074a8a76f35ec4484768b24b3606f08e1` | vibeic/connectivity-match | ✅ NEW (lvs-fidelity + J1) |
| magic | `19185c197fbaa4a91ec52877a2c13ec08a97b7ed` | vibeic/integration | unchanged (already on origin) |
| iverilog | `110cadd57c3a96ca81e84bdb0a78463e81575088` | vibeic/sv-tb-coverage | unchanged |
| verilator | `0782026557405c5ee7967a4975e9e6f20ee82154` | vibeic/sv-tb-coverage | unchanged |
| cocotb | `297211d359e81f6d48465e82752ef1866d1c8b0d` | vibeic/parallel-regression-dispatch | unchanged |
| cocotb-coverage | `be916da99520662f77cfccb8dd17861c8f986ce0` | vibeic/integration | unchanged |
| pyuvm | `f6ccec0ecebe504b209ac0cad74dc0716888a96f` | vibeic/integration | unchanged |
| sby | `37298228f565ab35549bd7b27c0551ddefb55802` | vibeic/integration | unchanged |
| ORFS | `v3.0` | (upstream tag) | now also supplies asap7 |

**All 12 refs verified reachable on their vibeic origin forks before build** (a fresh `docker build` clones + checks out each — a ref only in a local worktree will fail).

### OpenROAD consolidation content (1bade74e)
Merged 10 work branches + verify5 into one integration line. Authored + gated: **DR6** (LEF58_MINSTEP MAXEDGES, advanced-node DRC), **FP2** (ppl per-net-weight IO placement), **PD2/PD4** (PDN strap-sizing + decap-sizing inverses, independent-solver gates). Plus timing/fill/cts/dpl-leak work. Regression on the built binary: DR6 gcTest 3/3 + gc suite 104/104, PSM 54/54. `src/sta = 1e21c3f` (superset).

---

## 2. NEW this cycle — first-time publications a regen now depends on

### 2a. `vibeic/OpenSTA` fork (CREATED this cycle)
The OpenROAD `src/sta` submodule pins the **vibeic OpenSTA superset** `1e21c3f7752703212bb6d1b2aa6ca74cf271b38c` (branch `vibeic/sta-timing-eco`) = our signoff-SI + timing-ECO kernels (SI3/ST5/ST6/ST7 + ST2/CT2/PD3/SI2). **This work previously existed only in local worktrees and was never published** — the baseline `5a00b628` used upstream OpenSTA.
- Created `github.com/vibeic/OpenSTA` (fork of The-OpenROAD-Project/OpenSTA) and pushed `vibeic/sta-timing-eco`.
- The integration branch's `.gitmodules` was repointed: `[submodule "module/OpenSTA"] url = https://github.com/vibeic/OpenSTA.git` (was the relative `../../The-OpenROAD-Project/OpenSTA.git` → upstream, which does NOT have our commit).
- ⚠️ **REGEN INVARIANT:** any future OpenROAD ref whose `src/sta` points at a vibeic sta commit MUST keep `.gitmodules` pointing at vibeic/OpenSTA, and that commit MUST be pushed there, or the build fails with `upload-pack: not our ref`.

### 2b. ASAP7 PDK (ADDED this cycle)
ASU/ARM **7nm FinFET predictive PDK** (asap7sc7p5t 7.5-track), **BSD-3-Clause** — staged into `/foss/pdks/asap7` from the existing ORFS v3.0 sparse clone (`flow/platforms/asap7`, added to the nangate45-src sparse-checkout set).
- Staged: tech LEF `asap7_tech_1x_201209.lef`, cell LEF (RVT `asap7sc7p5t_28_R_1x_220121a.lef`), the 5 RVT-TT Liberty groups (4 gzipped → gunzipped via `zcat`, 1 plain SEQ), per-VT GDS, KLayout DRC deck `asap7.lydrc`. Registered in `programs/pdk_registry.json` (`tapeout_capable=false`, `lvs_deck=null`, no CDL).
- **tapeout_capable = FALSE** (predictive, not a real foundry — same class as nangate45/FreePDK45). Never claim silicon sign-off on asap7.
- ⚠️ **REGEN FOLLOW-UP:** `phase3_one_shot_runner.py`'s named-PDK path (~line 2240) hardcodes a single-liberty `PdkConfig` per PDK; `--pdk asap7` needs a 5-lib-aware branch for end-to-end resolution. Staging + registry are done; the runner branch is NOT yet wired.

### 2c. ngspice `--enable-openmp`
ngspice-builder configure now carries `--enable-openmp` (device-model eval OpenMP-parallel). libgomp linked; the banner doesn't advertise it (ngspice convention). Pairs with the plugin's default `OMP_NUM_THREADS` wiring (see §4).

---

## 3. NDA remediations completed this cycle (BINDING — do not regress)

### 3a. OpenROAD commit-message purge (force-pushed)
Two commit MESSAGES leaked a commercial-foundry SKU (tree content was clean). Purged via scoped `git filter-branch --msg-filter` (SKU → "commercial PDK") across THREE origin branches, all trees byte-identical, then force-pushed:
- `vibeic/openroad-integration`: 79fb5dc4 → 153e6916 (then the sta `.gitmodules` fix → **1bade74e**, the shipped ref)
- `vibeic/post-route-detailed-routing-repair-int`: → 94e03908
- `vibeic/post-route-detailed-routing-repair`: 5a00b628 → 9ad4084f (the residual base of an incomplete 2026-07-18 purge)
Origin scan after = 0 SKU hits on all three. No work lost (verified: 1cd84e50 was an ancestor, 0 ahead).

### 3b. Plugin source SKU scrub (vibe-ic marketplace) — IN PROGRESS at time of writing
The **published** plugin source (`origin/main` = v1.4.60 AND every user's installed cache) leaked the commercial-foundry name + SKU in **57 files' code comments**. Owner decision: **full history rewrite + republish**. Remediation underway: complete the divergent-history merge (45 local + 35 origin, keeping both) → scrub all 57 files' comments to "commercial PDK" → filter-repo the whole 943-commit history (repo has no upstream, so a global replace is safe) → force-push origin/main → republish as **v1.4.61** (users get the clean version on next update).

> ⚠️ **BINDING REGEN GATE:** before ANY fork push or image publish, scan commit messages AND source-comment content AND dir names AND `.gitignore` headers for foundry SKU/name/rule-id. This cycle caught TWO real leaks (OpenROAD msgs + plugin comments). Say "commercial PDK"; never the foundry name/SKU; never claim "silicon-proven".

---

## 4. Plugin-side parallel-by-default wiring (v1.4.61 — separate from the image)
An audit found the MCP `eda_*` tools invoked every tool SINGLE-THREADED (only yosys was parallel-by-default; the phase3 runner set OpenROAD threads). Wired parallel-by-default at the call layer (result-invariant, deterministic): `eda_pnr`/`eda_sta`/`eda_ir_drop`/`eda_sta_mcorner` → `-threads max`; `eda_drc_klayout` → `-rd threads=$(nproc)` (+ auto_drc_deck emits `threads()`); `eda_cocotb` → `make -j`; `eda_spice`/`_corner` → `OMP_NUM_THREADS=$(nproc)` (needs the §2c OpenMP build); verilator sim → `--build-jobs`. Single override env `VIBEIC_EDA_THREADS`. This ships in plugin v1.4.61, not the image.

---

## 5. Verification that gated 0.2.22 (all PASS)
- **12/12 forks present AND from our forks** (avoids the "green suite for the wrong pip package" trap): yosys `[vibeic/yosys]`, openroad `g1bade74e`, iverilog `g110cadd57`, verilator 5.048, ngspice-46+, klayout 0.30.9, magic 8.3.675, netgen 1.5.323; cocotb/cocotb-coverage/pyuvm all under `/opt/vibeic-forks/`, sby `v0.67-21-g3729822`.
- `/foss/pdks` = asap7 (NEW, 5 libs) + ciel + gf180mcuD + ihp-sg13cmos5l + ihp-sg13g2 + nangate45 + sky130A.
- OpenSTA `report_checks` present (superset in). ngspice libgomp linked.

---

## 6. Regen checklist (next time)
1. Re-poll each fork's origin; confirm every pinned ref is reachable on its vibeic fork (not just a local worktree). **Especially `src/sta` → vibeic/OpenSTA.**
2. NDA scan (msgs + source comments + dir names + .gitignore) on every ref before build. 0 hits required.
3. `DOCKER_BUILDKIT=1 docker build --network=host -t vibeic-eda:<next> .` (host net avoids the transient-DNS submodule-fetch failures seen this cycle).
4. Verify 12/12 forks from `/opt/vibeic-forks/` + `[vibeic/*]` markers; verify PDKs incl asap7; smoke tools.
5. Push `ghcr.io/vibeic/vibeic-eda:<next>`; bump `VERSION`; regen eda-forks.html with the new `image_version`.

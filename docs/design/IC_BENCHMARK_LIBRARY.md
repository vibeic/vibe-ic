# Cross-IC Benchmark Library — for v0.114+ plugin validation

10 application-specific ASIC IPs cloned to `/home/user/ic_documents/` (path note: `/home/` is root-owned, used `/home/user/`). Purpose: benchmark vibe-ic v0.114 plugin's spec-to-RTL flow on **single-purpose ASICs** beyond the bench-a IC-A reference. Provides the second axis of plugin validation — cross-chip generalisation, not just intra-chip iterations.

## Why this exists

Six release cycles (v0.108 → v0.114) iterated the plugin against a single benchmark project (bench-a IC-A). That validated **depth** — single-chip flow correctness. It does NOT validate **breadth** — does the same plugin work on chips it has never seen?

Cross-IC benchmark surfaces gaps the bench-a cycle can't:
- Doc-format assumptions baked into Phase 2a skills (e.g. AsciiDoc-only parsing)
- RTL idioms specific to one design style (Verilog-2001 vs SystemVerilog vs Migen-generated)
- L9 schema fields that bench-a has but other chips don't (or vice versa)
- Gates that systematically false-positive on commercial-grade RTL

## The 10 ICs

| # | Class | Chip | Repo | Best benchmark axis |
|---|---|---|---|---|
| 1 | Crypto (block cipher) | aes | secworks/aes | Phase 2a doc-extract on minimal-doc projects (1 README + bench file) |
| 2 | Crypto (hash) | sha256 | secworks/sha256 | Spec→RTL on small, well-defined algorithm |
| 3 | Crypto (hash) | sha1 | secworks/sha1 | Smallest benchmark — start here for first cross-IC run |
| 4 | Crypto (stream) | chacha | secworks/chacha | RFC 7539-conformance benchmark |
| 5 | Networking + bus | taxi | fpganinja/taxi | **Largest verification coverage** — Forencich's mono-repo (ex-verilog-ethernet/-pcie/-axi) |
| 6 | Memory controller | litedram | enjoy-digital/litedram | Migen-generated DDR controller — exposes generator-style assumption gaps |
| 7 | Storage | litesata | enjoy-digital/litesata | SATA Gen1/2/3, protocol state machines |
| 8 | Storage | litesdcard | enjoy-digital/litesdcard | SD/eMMC, simpler than SATA |
| 9 | High-speed link | liteiclink | enjoy-digital/liteiclink | Chip-to-chip SerDes / JESD204-style |
| 10 | Debug observability IP | litescope | enjoy-digital/litescope | Embedded logic analyzer (hardware) |

Total disk: 28 MB at clone time. Full INDEX with sizes / file counts / per-chip benchmark notes lives at `/home/user/ic_documents/INDEX.md`.

## Suggested benchmark protocol

For each chip, a fresh-agent run lives at `1st_benchmark_bench-a/2nd_benchmark_<chip>/` (parallel to existing v0108):

1. Copy the chip's `docs/` + `README.md` + any `.adoc/.rst/.pdf` to `2nd_benchmark_<chip>/input/docs/`. **Do NOT copy the chip's RTL** — that's the reference output.
2. Treat `input/docs/` as the only Phase 2a input. Run the v0.114 plugin's 17 Phase-2a skills.
3. Run Phase 2b spec-to-rtl. Generate RTL from L1-L9.
4. **Diff the agent-generated RTL against the chip's published RTL.**
   - Functional differences → BACKLOG-v11 candidate (Phase 2a/2b gap)
   - Stylistic differences → noted, not necessarily a gap
5. Where the chip ships a testbench, run it against agent-generated RTL. Does it pass?
6. Run Phase 3 (synth/STA/DFT/PnR/GDS) where toolchain supports.
7. Run `phase23_completion_self_audit_check.py --strict`. Compare verdict to the chip's published flow.

## Cross-chip patterns to log

If the same plugin issue surfaces on ≥3 of the 10 chips, that's a v11 BACKLOG candidate. Patterns to watch:

| Pattern | Likely root cause |
|---|---|
| All 4 crypto IPs fail Phase 2a | Doc-format assumption (secworks repos use minimal README + spec PDFs) |
| All Migen-style chips (litedram, litesata, litesdcard, liteiclink, litescope) fail Phase 2b | Generator-style design needs different lowering than pure Verilog |
| taxi sub-IPs fail because of submodule paths | Plugin assumes flat `rtl/` tree; taxi uses nested paths |
| All 10 fail Step 28 PV identically | Same KeyFoundry-class blocker — plugin issue, not chip issue |
| sha1 (smallest) PASS but larger ones FAIL | Plugin scaling issue |

## What this doesn't validate

- **Tape-out signoff fidelity** — only Caravel (which we removed for being a chip-harness, not an IC) had real GDS. None of these 10 ship full Sky130 tape-out artefacts. For real GDS comparison, supplement with OpenLane sample chips.
- **Mixed-signal flow** — these are all digital. Analog A1-A8 still benchmarks against bench-a OSC + bandgap.
- **Hardware-in-the-loop** — none of these have a published hardware reference verdict like bench-a's USB-HID tester. Cross-IC stops at RTL/sim level.

## Where to start

**Recommended first cross-IC benchmark**: `secworks/sha1` — only 8 RTL files, 2 doc files. Run completes quickly, surfaces the most basic gaps first. If sha1 passes cleanly, escalate to `aes` (slightly more, ECB+CBC modes), then `taxi` for the deep-dive.

## Versions / commits

All 10 cloned with `--depth 1`. To pin: `git -C /home/user/ic_documents/<chip> log -1 --pretty=oneline`.

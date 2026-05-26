# CVDP (Comprehensive Verilog Design Problems) — status & path to a citable number

## Honest status: NO citable pass-rate yet — three real blockers
CVDP is the benchmark that actually matches Vibe-IC's positioning (agentic, multi-file,
real EDA tools, cross-flow). But a citable CVDP pass-rate **cannot be produced from the open
repo alone** right now:

1. **The full benchmark is GATED.** The public `NVlabs/cvdp_benchmark` repo ships only an
   `example_dataset/` with **one problem per category** (e.g. `cvdp_agentic_fixed_arbiter_0001`,
   `cid003`/easy). The real 1,500+ problem set across 13 categories must be **requested from
   NVIDIA + Turing**. A pass-rate over 1-problem-per-category is meaningless.
2. **A model/agent backend must be wired.** This host has **no ANTHROPIC_API_KEY and no
   anthropic/OpenAI SDK**. CVDP offers two modes, each needs a backend we don't have wired:
   - **Non-agentic** (`README_NON_AGENTIC.md`): calls an OpenAI-compatible API (`openai==1.64.0`)
     to produce a patch → needs an API key + an Anthropic→OpenAI-compatible shim.
   - **Agentic** (`README_AGENTIC.md`): runs **your custom Docker agent** in a container; the
     harness tracks the agent's file changes and scores them. This is the mode that matches
     Vibe-IC — but it requires packaging Vibe-IC's Phase 1→3 flow as a CVDP-contract Docker agent.
3. **The OSS sim Docker image is GATED.** The harness's `docker-compose.yml` runs the cocotb
   testbench inside `OSS_SIM_IMAGE` (default `nvidia/cvdp-sim:v1.0.0`). `docker pull
   nvidia/cvdp-sim:v1.0.0` → **`pull access denied … repository does not exist or may require
   'docker login'`**. So even the example problem cannot be scored with the *official* image
   out-of-the-box. **Verified workaround:** the local `hpretl/iic-osic-tools` image carries
   `iverilog 13.0` + `cocotb 2.0.1` + `cocotb_tools` + `pytest`, i.e. everything the harness's
   `test_runner.py` needs (`SIM=icarus`); pointing `OSS_SIM_IMAGE` at a thin wrapper of it lets
   the `no_commercial` (Icarus) subset run locally. Any number produced this way must disclose
   the **substitute image + cocotb 2.x vs the harness's pinned version** as a deviation.

## Readiness verified (what DOES work)
- The harness + example dataset clone and ingest cleanly (NVlabs/cvdp_benchmark).
- `run_benchmark.py` runs once its Python deps (`requirements.txt`: nltk/openai/tiktoken/…)
  are installed; it exposes a **golden mode** (no `-l`/`-g` → apply golden patch + run harness,
  must PASS) and `--no-patch` (must FAIL) for harness-integrity checks.
- The example agentic `no_commercial` problem (`cvdp_agentic_fixed_arbiter_0001`, cid003/easy)
  loads with all fields: `prompt`, `context` (spec.md + cocotb TB), golden `patch`, `harness`
  (docker-compose + cocotb `test_runner.py`, `SIM=icarus`) — confirming we consume the format.
- Docker is available on the host. The official `OSS_SIM_IMAGE` is gated (blocker 3 above), but
  `hpretl/iic-osic-tools` provides a verified local substitute (iverilog 13 + cocotb 2.0.1).
  The `commercial` subset additionally needs Cadence Xcelium (absent).

## End-to-end demonstration done (N=1, substitute image) — see `DEMO_RESULT.md`
The full harness was actually run on the one open example problem with the local substitute
image: **golden → PASS**, **no-patch → FAIL** (harness discriminates), and **Claude-as-agent
→ PASS** (8/8) once the agent follows the in-context TB. It even surfaced a spec↔reference
inconsistency (spec says *synchronous* reset; reference + TB require *asynchronous*). This is a
smoke-test of the agentic loop, **not** a citable pass-rate — that still needs blockers 1 & 3
cleared. Details: [`DEMO_RESULT.md`](DEMO_RESULT.md).

## Path to a real, citable CVDP number
1. **Request the gated full dataset** from NVIDIA + Turing (CVDP access request). [draft below]
2. **Wire a backend** — recommended: package Vibe-IC as a **CVDP agentic Docker agent**
   (Phase 1→2→3 + the deterministic gates). This is the honest "agentic" measurement and plays
   to Vibe-IC's strength, vs the non-agentic single-API-call mode.
3. Run the **`no_commercial` (Icarus) subset** first for a clean, tool-available number; report
   the `commercial`/Xcelium subset only if/when a Cadence license is available — disclosed.
4. Score with the **official CVDP harness** (no custom scoring), report per-category pass-rates,
   no cherry-picking.

## Draft access request (to NVIDIA/Turing CVDP maintainers)
> We are evaluating an agentic RTL-design system (Vibe-IC: design-documents → RTL → synth → PnR
> → GDS → sign-off, with deterministic verification gates) and would like access to the full
> CVDP v1.x dataset to report official per-category pass-rates under the agentic workflow
> (Docker-agent mode). We will run the open-source / `no_commercial` (Icarus) subset and
> disclose any `commercial`/Xcelium-gated categories we cannot run. [contact / affiliation]

## Why this matters (positioning)
VerilogEval (we scored 93.59% pass@1, see `../verilogeval_v2/`) measures single-module RTL
generation. CVDP measures the agentic, multi-file, full-flow capability — i.e. exactly what
Vibe-IC is built for and what `benchmark_clean/` demonstrates qualitatively. A real CVDP number
would be the strongest external validation; it is gated on the two blockers above, documented
here honestly rather than approximated.

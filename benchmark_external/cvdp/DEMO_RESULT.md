# CVDP — local end-to-end demonstration (N=1, substitute sim image)

> **v0.1.5 re-run (2026-05-27).** Re-executed on v0.1.5 with the substitute image:
> golden → **PASS (1/1, 100%)**, no-patch (`-d`) → **FAIL (0%)** (harness discriminates), and the
> recorded Claude-as-agent TB-in-context RTL (`claude_agent_dataset_v2.jsonl`) → **PASS (1/1, 8/8
> tests, 100%)**. All three reproduced (matches the v0.1.4 re-run). **Scope unchanged: N=1 on the
> only open problem with a substitute sim image — still NOT a citable pass-rate** (blockers 1 & 3
> in `STATUS.md` remain).

> **v0.1.4 re-run (2026-05-27).** Re-executed on the v0.1.4 setup with the substitute image:
> golden → **PASS (1/1, 100%)**, no-patch (`-d`) → **FAIL (0%)** (harness discriminates), and the
> recorded Claude-as-agent TB-in-context RTL (`claude_agent_dataset_v2.jsonl`) → **PASS (1/1, 8/8
> tests, 100%)**. All three reproduced. **Scope is unchanged: N=1 on the only open problem, with
> a substitute sim image — still NOT a citable pass-rate** (blockers 1 & 3 in `STATUS.md` remain).

This records an **actual run** of the official CVDP harness on the one open example problem,
working around the three blockers in `STATUS.md`. It is **NOT a citable pass-rate** (N=1, and
the official sim image was substituted) — it proves the harness + a Claude agent run
end-to-end, and it surfaced a real spec/reference inconsistency.

## Setup (how the blockers were worked around)
- **Dataset:** only the open `example_dataset/` (1 problem/category) — full set still gated.
  Problem: `cvdp_agentic_fixed_arbiter_0001` (cid003, easy, `no_commercial`/Icarus).
- **Sim image:** official `nvidia/cvdp-sim:v1.0.0` is gated (`pull access denied`). Substituted
  a locally-built `cvdp-sim-local:latest` = `hpretl/iic-osic-tools` (iverilog 13 + cocotb 2.0.1
  + pytest) with the entrypoint reset and `PATH`/`PYTHONPATH`/`LD_LIBRARY_PATH` baked in so the
  harness's `docker-compose … command: pytest /src/test_runner.py` runs directly.
  `.env`: `OSS_SIM_IMAGE=cvdp-sim-local:latest`.
- **Backend:** no API key — so **Claude acted as the agent directly** (authored the RTL); the
  RTL was scored by the **unmodified official harness** (`run_benchmark.py` golden machinery,
  with the `patch` field carrying the agent's RTL).

## Results (official harness, `result: 0` = PASS)
| Run | Mode | Verdict |
|---|---|---|
| Harness integrity — golden patch | `run_benchmark.py -f <ds>` | **PASS** (100%, result 0) |
| Harness integrity — no patch | `run_benchmark.py -f <ds> -d` | **FAIL** (result 1) — discriminates correctly |
| Claude-as-agent, **blind-from-spec** (synchronous reset, as the spec literally states) | agent RTL via patch | **FAIL** — 7/8 testbench cases; fails only Test Case 8 |
| Claude-as-agent, **TB-in-context** (async reset, per CVDP agentic contract) | agent RTL via patch | **PASS** (8/8, result 0) |

## The instructive part: a spec ↔ reference inconsistency
- `docs/specification.md` says **"Active-high *synchronous* reset (clears all outputs)."**
- The reference RTL (`patch`, inspected post-hoc) actually implements **asynchronous** reset:
  `always @(posedge clk or posedge reset)`.
- The harness cocotb TB's **Test Case 8** ("reset during operation") reads `grant` immediately
  after asserting reset + one edge — which only reads 0 if reset clears **asynchronously**.
- A solution authored **blind from the spec wording** (synchronous) is *spec-correct* but fails
  TC8. CVDP's **agentic contract gives the agent the verification bench as context**, so the
  legitimate agentic move is to follow the TB (async reset) over the spec wording — that
  version passes 8/8. Both versions are recorded (`claude_agent_dataset*.jsonl`).

This is exactly the multi-file, spec-vs-bench reasoning CVDP is designed to measure — and the
kind of inconsistency Vibe-IC's own `spec-validator` / `spec-review` gates target.

## Honest scope
- **N = 1.** This is a smoke-test of the full agentic loop on the only open problem, not a
  pass-rate. A real number still needs the **gated full dataset** (blocker 1) and, for a clean
  comparison, the **official `nvidia/cvdp-sim` image** (blocker 3) rather than the substitute.
- Reproduce:
  ```bash
  cd cvdp_benchmark && echo "OSS_SIM_IMAGE=cvdp-sim-local:latest" > .env
  python3 run_benchmark.py -f example_dataset/..._agentic_..._no_commercial_with_solutions.jsonl -p golden_work        # golden -> PASS
  python3 run_benchmark.py -f example_dataset/..._agentic_..._no_commercial_with_solutions.jsonl -p nopatch_work -d     # no patch -> FAIL
  python3 run_benchmark.py -f claude_agent_dataset_v2.jsonl -p claude_work_v2                                           # Claude agent -> PASS
  ```

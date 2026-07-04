# CVDP legal-input definition (compliance line) — evidence-grounded

**Dataset:** `cvdp_v1.1.0_nonagentic_code_generation_no_commercial` (302 problems)
**Sources:** NVlabs/cvdp_benchmark `README_NON_AGENTIC.md` (JSON schema) + empirical
per-category map of the 302 records + paper arXiv:2506.14074 §2.

## The record schema (README_NON_AGENTIC.md, authoritative)
```json
{
  "id": "...", "categories": ["cidNNN","difficulty"],
  "input":  { "prompt": "...", "context": { "path": "content" } },   // ← MODEL INPUT
  "output": { "context": { "path": "reference content" } },          // ← HELD BACK (reference)
  "harness":{ "files":   { "docker-compose.yml": "...", "test_*.py": "..." } } // ← HELD BACK
}
```

## The AUTHORITATIVE distinction (paper arXiv:2506.14074, verbatim)
> "We distinguish between the **testbench** (SystemVerilog provided in-context) and the
> **test harness** (used only for evaluation). Models or agents may generate or use a
> testbench but **never see the test harness or reference solution**."

So in GENERAL there are THREE tiers, not two:
- **testbench (SystemVerilog), provided in-context** → **LEGAL** (model may see/use/generate it).
- **test harness (cocotb Python `test_*.py` + `harness_library.py` + docker-compose + .env)** → **HELD BACK** (evaluation-only).
- **reference solution / patch (`output.context`)** → **HELD BACK** (stripped; KEYS = deliverable layout).

"Oracle context" philosophy: the model gets *only the minimal relevant info needed* — all
necessary info IS in prompt + context; nothing extra to retrieve.

## LEGAL INPUT = `input.prompt` + `input.context` (`input.context` MAY legally include a SystemVerilog TB, worked-examples, observed-expected tables)
Held back (reading them = non-compliant / oracle-peeking):
- `harness.files` — the cocotb **test harness** (`test_*.py`, `harness_library.py`,
  `docker-compose.yml`, `.env` TOPLEVEL, `.vlt` lint waiver, `.tcl` synth scripts).
- `output.context` — the reference/golden deliverable.

### EMPIRICAL: for THIS 302 no_commercial subset the SV-testbench tier is EMPTY
Precise scan (SV-TB = `.sv/.v` whose name/body is a testbench, distinct from a `.py` cocotb harness):
- `input.context`: 141 `.sv/.v` files, **0 are SystemVerilog testbenches** (all are partial/buggy DUT RTL).
- `harness.files`: **0 `.sv` TB, 810 `.py`** — the harness is PURELY cocotb Python (held back).
- prompt bodies: **0 embedded TBs**.

⇒ No problem in these 302 legally provides a testbench. So the general TB-in-context tier, while
real, does NOT widen the line here: **legal input for all 302 = `input.prompt` + `input.context`
(partial/buggy RTL + spec docs + any worked-example/observed-expected tables), and the cocotb
harness + reference are uniformly held back.** (The TB-in-context tier WOULD matter for CVDP
tracks that ship an SV testbench in-context — not present in this subset.)

## Empirical per-category map of the 302 (what input.context actually contains)

| cid | task | n | input.context (LEGAL) | TB in input.context? | harness (HELD BACK) | output.context (HELD BACK) |
|---|---|---|---|---|---|---|
| cid002 | code-completion | 94 | partial RTL (some) | **0/94** | TB + docker + .env | reference RTL |
| cid003 | spec→RTL | 78 | spec doc (mostly in prompt) | **0/78** | TB + docker + makefile | reference RTL (+2 TB) |
| cid004 | RTL-modify | 55 | RTL to modify + spec | **0/55** | TB + docker | reference RTL |
| cid007 | RTL-improve/PPA | 40 | RTL to optimize | **0/40** | TB + docker + .tcl + .vlt | reference RTL |
| cid016 | debug/bugfix | 35 | buggy RTL + spec | **0/35** | TB + docker | reference RTL |

## KEY FINDING — legal input is UNIFORM in this subset
**Across ALL 5 categories, ZERO problems place the testbench in `input.context`.**
The TB is ALWAYS in `harness.files` (held back). So there is NO "prompt+TB legal"
problem here — the worry that some problems legally provide the TB does NOT apply to
this no_commercial subset. Legal input for EVERY one of the 302 is:

> **`input.prompt` (task + usually the full Port List / interface table) + `input.context`
> (partial/buggy RTL and/or a spec doc). The testbench, .env TOPLEVEL, reference RTL, and
> synth/lint configs are ALL held back.**

(TB-as-legal-input WOULD apply to other CVDP tracks — cid012–014 testbench-generation,
or the commercial subset — but none are in these 302.)

## Consequence for the "59 floor" question
A residual fail is a GENUINE (compliant) floor ONLY if the failing requirement lives
ONLY in a held-back file (harness TOPLEVEL/port-name the prompt never states; a TB-internal
assertion value; an exact area threshold in a .tcl) — i.e. `spec-absent` from prompt+context.
It is NOT a floor (it is expert-recoverable, compliant) if the failing requirement is:
- present in `input.prompt`/`input.context` but we mis-extracted/mis-authored it, OR
- resolvable by genuine DOMAIN CONVENTION a panel of experienced designers would converge on
  (standard interface names, algorithm correctness, conventional reset/latency) — this is
  "convention-inference", the §4 agent-fixable class, and does NOT require reading the harness.

The v1.2.63 compliant gate (reads only input.prompt + input.context) correctly enforces
this line; the expert re-attempt experiment stays compliant by reading the SAME two fields
only, never harness.files / output.context.

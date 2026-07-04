# Unified DOC→JSON Phase-1 backend + dialogue dual-track convergence — RESULT

**Owner directives (2026-06-20):**
1. CVDP's 302 concrete specs must go through the **DOC→JSON** path (document →
   L1-L24 JSON), not the weak engine "prompt" reverse-extractor — and the
   runner routing must be fixed to make that automatic.
2. **Every** Phase-1 front-end must converge to ONE backend (DOC→JSON), so all
   previously-trained doc-extraction programs are reused and the emitted JSON
   is **homogeneous regardless of input source**. A dialogue is just a freestyle
   document.
3. The dialogue path is a **dual-track convergence** owned by the IC-Expert
   Agent: program DOC→JSON + an independent AI read → compare → synthesize →
   confirm sufficiency (ask the user, in plain language, only if a required
   fact is genuinely missing).
4. **Merge** the PM Agent into the IC-Expert Agent (one dual-register role; no
   separate PM).

## Architecture shipped

```
            ┌─ input/docs/ (real vendor docs) ───────────────┐
front-ends ─┼─ input/phase1_prompt.md (raw prose, e.g. CVDP) ─┼─► render-bridge ─► ONE
            └─ input/phase1_structured.yaml (dialogue) ───────┘   (freestyle doc)   DOC→JSON track
                                                                                   (phase1_doc_one_shot_runner)
                                                                                          │
                                              homogeneous L1-L24 JSON  ◄─────────────────┘
```

- **Routing fixed** — `phase1_one_shot_runner._detect_input_mode` and the top
  orchestrator `vibe_ic_one_shot_runner._phase1_decision` now resolve a
  free-text prompt AND a dialogue fact-graph to **docs**. `_run_docs_mode`
  render-bridges each into `input/docs/` before ingestion. The legacy engine
  reverse-extractor stays reachable only via an explicit `--mode prompt`.
- **`phase1_dialogue_render.py`** (new) — renders a dialogue artifact
  (`phase1_structured.yaml` fact-graph, or a raw transcript) into a freestyle
  design-description document, emitting the structural forms (a port table for
  record-lists) the doc-track extractors re-anchor on. A round-trip recovered
  all 7 ports of a 5-port dialogue.
- **`phase1_json_converge.py`** (new) — the deterministic half of the dialogue
  dual-track convergence: diffs program-track vs AI-track L1-L24 JSON
  fact-by-fact (agree / disagree / one-sided), order-independent by identity,
  numeric-aware; emits a `merged_candidate` carrying `_conflict` markers for
  the IC-Expert Agent to resolve. Never accepts a lone track.
- **`phase1_sufficiency_check.py`** — the deterministic sufficiency gate: from
  the converged L1, checks the minimum buildable contract (a name + ≥1 port)
  and, for each missing REQUIRED fact, emits a **plain-language, no-jargon**
  question for the user. Clock/reset are **advisory, never blocking** (fixed a
  found over-demand false-positive — see below).
- **PM→IC-Expert merge** — one dual-register IC-Expert Agent (internal
  technical register for JSON/convergence/sufficiency; external plain-language
  register, no silicon jargon, when facing the user). `pm-agent` kept as an
  alias so existing wiring resolves; `skills/phase1` invokes the IC-Expert
  directly. *(agent-markdown edits in this PR; personas remain as test drivers
  that validate the no-jargon guarantee.)*

## Headline result — all 302 CVDP through unified doc mode (deterministic, no LLM)

| metric | value |
|---|---|
| produced full **24/24 L docs** | **302 / 302** |
| L1 **deterministically sufficient** (name + ports) | **284 / 302 (94%)** |
| need the AI track (L1 port_count == 0) | 18 / 302 |
| L1 ports extracted | min 0 · mean **8.7** · max 110 |

This is the honest **program-first / AI-backup split**: the deterministic
DOC→JSON track now carries 94% of the 302 concrete specs to a buildable L1 by
itself (vs the old engine "prompt" path, which reverse-extracts only
pre-structured `L*.json` and yields **0 facts on raw prose**). The 18 residual
are where the program track found no ports — the legitimate hand-off to the
IC-Expert AI track.

## A real defect this campaign caught and fixed (dual-track in action)

The first sufficiency sweep flagged **243/302 "insufficient"** — but with an
EMPTY `missing_required`. Root cause: `_is_sequential` inferred "sequential"
from the mere presence of L6/L8/L12 **skeleton hint strings** (every project
emits a 24-layer scaffold), so it over-demanded a clock/reset on purely
**combinational** parts — exactly the known false-"insufficient" class. Fix:
`_is_sequential` keys on a real clock/reset port only, and clock/reset are
**advisory, never blocking**. After the fix: **284 sufficient, 18 insufficient
— all 18 genuine** (`missing_required: ['ports']`, port_count 0). A green lone
gate had masked a real over-demand; the cross-check converged it.

## Honest residual → filed, not discarded (fix-all-into-the-plugin)

Spot-checking the 18 showed two are NOT irreducible free prose but recoverable
**structured-prose** forms the L1 bullet-port extractor misses:
`- [7:0] name: desc` (width-prefixed) and `- **name**: desc` (markdown-bold).
Filed as **Bucket C** —
`community/backlogs/ORGANIC-20260621-l1-bullet-port-width-prefix-and-bold-name.yaml`
— because `_l1_bullet_port_extract` is a heavily-patched, false-positive-
sensitive subsystem (#116/#118/v1.6.257/258) that needs its own corpus-swept
PR, not a change bundled into the architecture PR. Shrinking the 18 is the
next program-first step.

## Tests

- `programs/tests/test_phase1_unified_docjson.py` (new, 14 tests) — routing
  (every front-end → docs; pre-structured L*.json → legacy prompt), dialogue
  render (port-table emission + transcript pass-through), convergence
  (agree / value-disagree → `_conflict` / one-sided / numeric-string
  equivalence), sufficiency (sufficient; insufficient → no-jargon questions;
  combinational does-not-overdemand-reset).
- `test_v0_3_39_issue583_phase1_mode_priority.py` — updated to the unified
  contract (all front-ends → docs), preserving the surviving #583 invariant: a
  prompt's content is never lost to a `.gitkeep`-only docs/ (carried by the
  render-bridge), never a SKIP.
- Full phase1/orchestrator/specrtl regression: green except **2 pre-existing
  failures** (`test_bundle_does_not_drift_from_master`, an issue-689 reset_n
  alias test) that fail on **clean main** too — not introduced here.

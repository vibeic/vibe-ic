#!/usr/bin/env python3
"""emit_author_context.py — stage the IC-Expert design-class DIGEST for a blind
Shape-B / Shape-C author, derived from the PROMPT ONLY (§4.05-safe).

WHY (RULE-0 compliance, 2026-07-06): the lightweight benchmark harnesses
(gates_atomic.py for Shape C, the Shape-B blind authoring loop) had the AI-backup
author RTL from the raw prompt with NEITHER expert asset loaded — a transcript
audit of a full VE-v2 / VE-Human / RTLLM blind sweep found ZERO `ic_expert_db_query`
calls and ZERO `agents/lessons` reads across all authors. The authors carried the
IC-Expert *identity* (subagent type / system-prompt) but never consulted the two
concrete expert assets RULE 0 mandates. This program closes that: it renders the
RELEVANT expert-DB design-class craft for the design under authoring into the work
dir, so the blind author actually consumes it BEFORE writing RTL.

WHAT IT EMITS (into <out-dir>):
  * ic_expert_db.md  — the top-k design-class lessons matched to THIS prompt
    (via programs/ic_expert_db_query.py → _lesson_digest.render_ic_expert_db_digest).
    Small + prompt-targeted: the plugin's own A/B (2026-07-02, 94 CVDP designs)
    proved that folding the FULL 267KB `### Skill:` corpus into one author DILUTES
    attention and LOWERS recovery (38→31), whereas the compact, prompt-matched DB
    digest is the value-add for a DB-informed author (general-blind ∪ DB = +13).
    So we stage ONLY the targeted DB digest here, never the whole corpus.

§4.05 NO-LEAK: reads ONLY the prompt file. Never opens the oracle (_test.sv /
_ref.sv / testbench.v / verified_*.v). The digest is ADVISORY design-craft; the
deterministic gates still decide PASS.

Usage:
    emit_author_context.py --prompt <prompt_file> --out-dir <work/<prob>>
    # writes <out-dir>/ic_expert_db.md ; prints the count of lessons staged.
Exit 0 always (a design with no DB match simply stages nothing — not an error).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../benchmark/
PROGRAMS = HERE.parent / "programs"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt file (INPUT only — never the oracle)")
    ap.add_argument("--out-dir", required=True, help="work dir for this design (<run>/work/<prob>)")
    ap.add_argument("--k", type=int, default=5, help="top-k DB lessons to stage")
    a = ap.parse_args()

    prompt = Path(a.prompt)
    if not prompt.is_file():
        print(f"NO_PROMPT {prompt}", file=sys.stderr)
        return 0
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    try:
        import _lesson_digest as _ld
    except Exception as e:  # noqa: BLE001
        print(f"DIGEST_MODULE_UNAVAILABLE {e}", file=sys.stderr)
        return 0

    n = _ld.render_ic_expert_db_digest(out, prompt.read_text(errors="replace"), k=a.k)
    if n:
        print(f"staged {n} expert-DB design-class lesson(s) -> {out / 'ic_expert_db.md'}")
    else:
        print("no expert-DB match for this prompt (staged nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

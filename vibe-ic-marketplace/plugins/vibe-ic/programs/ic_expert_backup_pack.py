#!/usr/bin/env python3
r"""ic_expert_backup_pack.py — assemble the IC-Expert-Agent AI-backup context pack.

GENERAL CORE (benchmark-AGNOSTIC). When a deterministic track cannot author a
body (the common case — a non-standard design), the plugin's answer is NOT a
generic LLM: it is to let the AI act AS the **IC Expert Agent**, USING the two
expert assets the agent owns —

  * expert-SKILLS — the ACTIVE `### Skill:` sections distilled in
    `agents/ic-expert-agent.md` (rendered to `lessons.md` by
    `_lesson_digest.render_lesson_digest`);
  * expert-DB   — the design-class craft in `agents/ic_expert_db/ic_expert_db.json`,
    retrieved for THIS prompt by `ic_expert_db_query.query` and rendered to
    `ic_expert_db.md` by `_lesson_digest.render_ic_expert_db_digest`.

A MEASURED A/B lesson (see `_lesson_digest.render_lesson_digest` note: folding the
DB into the one skills digest LOWERED single-shot recovery 38→31; the two as
INDEPENDENT authors reached 51) makes this a **DUAL-TRACK** hand-off, not one
blob:

  * Track 1 — general-blind author: prompt + interface contract + `lessons.md`.
  * Track 2 — DB-informed author:  prompt + interface contract + `ic_expert_db.md`.
  * Converge — a comparator diffs the two bodies; disagreement is root-caused and
    reconciled (the program-first + AI-backup dual-track convergence doctrine).

This module does the DETERMINISTIC assembly (retrieve + render + write the
contract + emit the hand-off descriptor). The actual LLM authoring is performed
by invoking the `vibe-ic:ic-expert-agent` subagent on the emitted pack — the
hand-off JSON names exactly that invocation, so an orchestrator (a benchmark
driver, `phase1-orchestrate`, or a human) runs it identically. Reads ONLY the
supplied prompt + interface — never any oracle/harness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

SUBAGENT_TYPE = "vibe-ic:ic-expert-agent"


def iface_to_contract_v(iface: List[Dict[str, Any]], target: str) -> str:
    """Header-only `module <target> ( … ); endmodule` from a recovered interface
    — the CONTRACT the AI-backup body must satisfy. Ports only, no behaviour."""
    body = []
    for p in iface or []:
        d = p.get("dir") or "input"
        w = p.get("width")
        rng = f" [{int(w) - 1}:0]" if isinstance(w, int) and w and w > 1 else ""
        body.append(f"  {d}{rng} {p.get('name')}")
    return f"module {target} (\n" + ",\n".join(body) + "\n);\nendmodule\n"


def _db_hits(prompt: str, k: int) -> List[Dict[str, Any]]:
    try:
        import ic_expert_db_query as _db
        hits = _db.query(prompt, k=k) or []
    except Exception:
        return []
    out = []
    for h in hits:
        if isinstance(h, dict):
            out.append({"ic_class": h.get("ic_class"),
                        "score": round(float(h.get("score", 0) or 0), 2)})
    return out


def _spec_requirements(prompt: str,
                       context_keys=None) -> List[Dict[str, Any]]:
    """Run the deterministic spec detectors on the prompt (+ `input.context` file
    keys) and return the concrete, chip-agnostic requirements an author would
    otherwise silently drop. These are the distilled RCA rules (issue #126): an
    addressable memory region behind the same bus as the CSRs (extraction-gap), a
    lint-review deliverable whose graded axis is `verilator -Wall` cleanliness
    (coverage-gap), and a context-sibling collision advisory (never inline a
    verbatim copy of a separately-compiled context module). Input-only."""
    reqs: List[Dict[str, Any]] = []
    try:
        import spec_memory_region_detect as _mem
        r = _mem.detect_memory_region(prompt)
        if r.get("has_memory_region") and r.get("requirement"):
            reqs.append({
                "kind": "memory_map_completeness",
                "confidence": r.get("confidence"),
                "requirement": r["requirement"],
                "evidence": r.get("evidence", [])[:3],
            })
    except Exception:
        pass
    try:
        import spec_lint_review_detect as _lint
        r = _lint.detect_lint_review(prompt)
        if r.get("is_lint_review") and r.get("requirement"):
            reqs.append({
                "kind": "lint_review_selfgate",
                "requirement": r["requirement"],
                "self_gate": "verilog_selfcheck_lint.py (verilator --lint-only -Wall)",
                "issues_requested": r.get("issues_requested", []),
            })
    except Exception:
        pass
    try:
        import spec_context_sibling_detect as _sib
        r = _sib.detect_context_siblings(prompt, context_keys)
        if r.get("has_siblings") and r.get("requirement"):
            reqs.append({
                "kind": "context_sibling_no_inline",
                "requirement": r["requirement"],
                "sibling_modules": r.get("sibling_modules", []),
                "prose_excluded": r.get("prose_excluded", []),
            })
    except Exception:
        pass
    try:
        import spec_selftb_coverage_detect as _stb
        r = _stb.detect_selftb_coverage(prompt)
        if r.get("shapes") and r.get("requirement"):
            reqs.append({
                "kind": "self_tb_coverage",
                "requirement": r["requirement"],
                "shapes": r.get("shapes", []),
                "authoring_invariants": r.get("authoring_invariants", []),
                "self_tb_scenarios": r.get("self_tb_scenarios", []),
                "parameter_sweeps": r.get("parameter_sweeps", []),
            })
    except Exception:
        pass
    try:
        import spec_named_signal_detect as _sig
        r = _sig.detect_named_signals(prompt)
        if r.get("has_named_signals") and r.get("requirement"):
            reqs.append({
                "kind": "preserve_named_signals",
                "requirement": r["requirement"],
                "named_signals": r.get("named_signals", [])[:20],
            })
    except Exception:
        pass
    return reqs


def assemble(prompt: str, iface: Optional[List[Dict[str, Any]]], target: Optional[str],
             expert_skills: List[str], verify_gates: List[str],
             out_dir: Path, k: int = 5, context_keys=None,
             output_target: str = "rtl.sv") -> Dict[str, Any]:
    """Assemble the IC-Expert-Agent AI-backup pack into `out_dir`. Returns the
    hand-off descriptor (also written to `out_dir/ic_expert_agent_handoff.json`).
    `context_keys` (optional) = the record's `input.context` file paths, used for
    the context-sibling collision advisory.

    `output_target` names the artefact the agent is asked to author. It defaults
    to `rtl.sv` — the RTL-authoring hand-off this module was built for.
    The assembly itself (retrieve, render the two INDEPENDENT digests, write the
    contract, emit the descriptor) is target-agnostic, so the Phase-1 expert
    PARSE track reuses it verbatim with `l_doc_expectations.json`. Same dual-
    track hand-off, different question asked of it — reusing it is what keeps
    one measured mechanism instead of two similar ones drifting apart."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = prompt or ""

    # expert-SKILLS digest (Track 1) + expert-DB digest (Track 2).
    n_skills = n_db = 0
    try:
        import _lesson_digest as _ld
        n_skills = _ld.render_lesson_digest(out_dir)
        n_db = _ld.render_ic_expert_db_digest(out_dir, prompt, k=k)
    except Exception:
        pass
    db_classes = _db_hits(prompt, k)

    # interface CONTRACT (the load-bearing spec the body must honour).
    contract_rel = None
    if iface and target:
        (out_dir / "contract.v").write_text(iface_to_contract_v(iface, target))
        contract_rel = "contract.v"

    handoff = {
        "subagent_type": SUBAGENT_TYPE,
        "role": "IC Expert Agent authors the body using expert-DB + expert-skills",
        "prompt_is_input_only": True,
        "target_module": target,
        "interface_contract": contract_rel,
        "spec_requirements": _spec_requirements(prompt, context_keys),
        "expert_skills": expert_skills,
        "verify_gates": verify_gates,
        "db_classes": db_classes,
        "dual_track": {
            "track1_general_blind": {
                "context": ["lessons.md"] if n_skills else [],
                "n_skills": n_skills,
            },
            "track2_db_informed": {
                "context": ["ic_expert_db.md"] if n_db else [],
                "n_db_lessons": n_db,
            },
            "converge": "diff the two bodies; root-cause + reconcile disagreement",
        },
        "output_target": output_target,
    }
    if output_target == "l_doc_expectations.json":
        # Phase-1 expectation authors compare generated L-docs. State the
        # generated schema explicitly: source documents may use different
        # historical layer numbers, but the generated contract does not.
        # The pack must also carry the INPUT it asks the agent to review. The
        # old descriptor named an output and two lesson digests but did not
        # contain the design input, so an orchestrator could dispatch it only
        # by inventing another, undocumented read surface (#1973).
        input_name = "design_input.txt"
        (out_dir / input_name).write_text(prompt)
        handoff["read_design_input_from"] = input_name
        handoff["generated_layer_contract"] = {
            "L9": "integration specification",
            "L19": "constraints and implementation context",
        }
        handoff["answer_contract"] = {
            "schema": "vibeic.phase1-expert-expectations.v1",
            "minimum_expectations": 1,
            "shape": {
                "expectations": [{
                    "id": "stable rule-and-subject identifier",
                    "layer": "generated L-layer name",
                    "field_path": "optional field path",
                    "requirement": "what the input requires the layer to carry",
                    "evidence": ["input-only evidence supporting the expectation"],
                    "expected_tokens": ["one or more tokens to compare"],
                }],
            },
            "rules": [
                "read only design_input.txt plus the two expert digests",
                "never read an oracle, harness, golden artifact, or hidden answer",
                "write the JSON object to l_doc_expectations.json",
                "an empty expectations list is incomplete, not a completed review",
            ],
        }
    (out_dir / "ic_expert_agent_handoff.json").write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False))
    return handoff


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default=None)
    ap.add_argument("--skills", default="", help="comma list of expert skills")
    ap.add_argument("--verify", default="", help="comma list of verify gates")
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    h = assemble(prompt, None, a.target,
                 [s for s in a.skills.split(",") if s],
                 [s for s in a.verify.split(",") if s],
                 Path(a.out), k=a.k)
    print(json.dumps(h, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

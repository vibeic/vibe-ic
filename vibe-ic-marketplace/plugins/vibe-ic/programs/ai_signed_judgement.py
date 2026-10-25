"""Evidence-bound AI judgement for the eight conditional expert hand-offs.

The program gates remain authoritative for mechanical checks. This BLOCKING
check only prevents their PASS tier from claiming the separate expert review.
Receipt: reports/audit/ai_judgements/<step>.json, schema
``vibeic.ai-judgement.v1``. The reviewer signs by naming the step, judgement,
their identity, and the SHA-256 of the exact files returned by evidence().
Review content must come from the reviewer. The Step3 CLI transports that
authored role answer to the same canonical receipt after source admission;
it never authors roles or grants a deterministic gate PASS.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple

SCHEMA = "vibeic.ai-judgement.v1"
STEPS = frozenset(("D1", "1", "3", "4", "5", "A1", "A2", "A9", "36"))
#: Step 5's one formal directory (`_path_layout.formal_dir`).
FORMAL_DIR = "phase2/stage1/formal"
#: Existing Phase1/D1 original-input population, shared with Step3 role review.
DESIGN_INPUT_GLOBS = ("input/design_input.txt", "input/phase1_prompt.md",
                      "input/phase1_structured.yaml", "input/docs/**/*",
                      "phase1/input_doc/**/*")


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _files(project: Path, *patterns: str) -> list[Path]:
    return sorted({p for pattern in patterns for p in project.glob(pattern)
                   if p.is_file()})


def evidence(project: Path, step_id: str) -> list[Path]:
    """The exact producer/AI output bytes reviewed, excluding audit writes."""
    sid = str(step_id)
    if sid == "3":
        import _cdc_netlist as native
        project = Path(project).resolve()
        path, _nl, binding = _reset_context(project)
        return sorted(set([path, path.parent / Path(native.NETLIST_LOG_REL).name,
                           path.parent / Path(native.NETLIST_MANIFEST_REL).name]
                          + [project / row["path"] for row in binding["input"]["files"]]
                          + _intent_files(project)))
    if sid == "D1":
        return _files(project, *DESIGN_INPUT_GLOBS,
                      "phase1/behavioral_refinement.facts.yaml",
                      "plugin_input/qualified-outputs.json",
                      "plugin_input/interface-bindings.json",
                      "plugin_input/interface_context/**/*",
                      "reports/phase1/interface_binding/proof.json",
                      "reports/phase1/interface_binding/execution.json",
                      "reports/phase1/interface_binding/type_probe.sv",
                      "reports/phase1/interface_binding/elaboration.log",
                      "reports/phase1/interface_binding/measurements.log",
                      "phase1/generated_docs/L*.json",
                      "reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json")
    if sid == "1":
        return _files(project, "phase2/stage1/fallback_skill.md",
                      "phase2/stage1/rtl/*.v", "phase2/stage1/rtl/*.sv",
                      "plugin_output/declaration.json",
                      "phase1/generated_docs/L*.json")
    if sid == "4":
        return _files(project, "phase2/stage1/sim_professional/**/expert_reference_tb.py",
                      "phase2/**/expert_reference_tb.py",
                      "reports/phase2/gates/professional_tb.json",
                      "phase1/generated_docs/L*.json")
    if sid == "5":
        # Expert properties live in the fragment, or in the harness itself
        # when no harness could be generated; a signature that did not cover
        # both would outlive a weaker property under the same name. Only the
        # formal directory's own files: sby copies sources into
        # <task>/src/, and those scratch copies are not the reviewed bytes.
        return _files(project, *(f"{FORMAL_DIR}/{name}" for name in (
            "formal_authoring_request.json", "formal_expert_review.json",
            "formal_expert_properties.svh", "formal_*.sv",
            "property_contract.json")), "phase1/generated_docs/L*.json")
    if sid == "A1":
        return _files(project, "phase3/analog/*/spec_gap.json",
                      "phase3/analog/*/spec.json", "phase1/analog/*/spec_gap.json",
                      "phase1/analog/*/spec.json",
                      "phase1/generated_docs/L5*.json")
    if sid == "A2":
        return _files(project, "phase3/analog/*/topology_gap.json",
                      "phase3/analog/*/topology.json",
                      "phase3/analog/*/topology.md",
                      "phase3/analog/*/spec.json",
                      "phase2/analog/*/topology_gap.json",
                      "phase2/analog/*/topology.md",
                      "phase1/generated_docs/L5*.json")
    if sid == "A9":
        return _files(project, "phase3/mixed_signal/cosim/*_cosim_results.json",
                      "phase3/mixed_signal/cosim/mixed_signal_results.json",
                      "phase3/analog/*/spec.json",
                      "phase1/generated_docs/L5*.json")
    if sid == "36":
        # Physical exception review; Step38 owns the final package checklist.
        return _files(project, "reports/phase3/layout_receipts.json",
                      "phase3/final/metrics.json",
                      "reports/phase3/signoff_metrics_aggregate.json",
                      "waivers.json", "reports/phase3/perc_equivalent.json")
    return []


def _requested(project: Path, sid: str) -> bool:
    if sid == "3":
        import _cdc_netlist as native
        path = project / native.NETLIST_REL
        try:
            return bool(native.reset_role_candidates(native.load(path)))
        except native.Refusal:
            # A removed/unreadable graph cannot erase an existing handoff.
            return path.exists() or (project / "reports/audit/ai_judgements/3.json").exists()
    if sid == "D1":
        return bool(_files(project, "phase1/generated_docs/L*.json"))
    if sid == "1":
        if not _files(project, "phase2/stage1/fallback_skill.md"):
            return False
        # A previous WAIVE's hint may remain after a later deterministic
        # generator run. The existing provenance ledger owns this distinction.
        import rtl_provenance
        return rtl_provenance.classify(project)[0] != rtl_provenance.GENERATED
    if sid == "4":
        return ((_json(project / "reports/phase2/gates/professional_tb.json")
                 .get("dut_kind") == "expert_reference")
                or bool(_files(project, "phase2/**/expert_reference_tb.py")))
    if sid == "5":
        # formal_harness_gen and formal_property_run delete the request once
        # the expert's answer closes it, so the answer itself keeps the
        # hand-off open until a receipt signs it.
        return bool(_files(project, f"{FORMAL_DIR}/formal_authoring_request.json",
                            f"{FORMAL_DIR}/formal_expert_review.json",
                            f"{FORMAL_DIR}/formal_expert_properties.svh"))
    if sid == "A1":
        return bool(_files(project, "phase3/analog/*/spec_gap.json",
                            "phase1/analog/*/spec_gap.json"))
    if sid == "A2":
        return bool(_files(project, "phase3/analog/*/topology_gap.json",
                            "phase2/analog/*/topology_gap.json"))
    if sid == "A9":
        return bool(_files(project, "phase1/analog/analog_block_list.json",
                            "phase3/mixed_signal/cosim/*_cosim_results.json",
                            "phase3/mixed_signal/cosim/mixed_signal_results.json"))
    if sid == "36":
        perc = _json(project / "reports/phase3/perc_equivalent.json")
        return (bool(_json(project / "waivers.json"))
                or any(isinstance(row, dict) and row.get("status") == "MANUAL_REVIEW"
                       for row in (perc.get("categories") or [])))
    return False


def evidence_sha256(project: Path, step_id: str) -> Optional[str]:
    files = evidence(project, step_id)
    if not files:
        return None
    digest = hashlib.sha256()
    try:
        for path in files:
            rel = path.relative_to(project).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(rel).to_bytes(8, "big"))
            digest.update(rel)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    except OSError:
        return None
    return digest.hexdigest()


def check(project: Path, step_id: str, *, expected_verdict: str = "PASS") -> Tuple[bool, str]:
    """Validate a current signed review; only PASS grants hand-off credit.

    The optional FAIL query lets transitions distinguish a measured rejection
    from an absent or stale review using the same evidence validator.
    """
    if expected_verdict not in ("PASS", "FAIL"):
        raise ValueError("expected_verdict must be PASS or FAIL")
    sid = str(step_id)
    if sid not in STEPS or not _requested(project, sid):
        return True, "no conditional AI hand-off"
    # A signature over a request alone cannot stand in for the work requested.
    required_ai_output = {
        "1": ("phase2/stage1/rtl/*.v", "phase2/stage1/rtl/*.sv"),
        "4": ("phase2/**/expert_reference_tb.py",),
        "5": (f"{FORMAL_DIR}/formal_expert_review.json",),
        "A1": ("phase3/analog/*/spec.json", "phase1/analog/*/spec.json"),
        "A2": ("phase3/analog/*/topology.json", "phase3/analog/*/topology.md",
               "phase2/analog/*/topology.md"),
        "A9": ("phase3/mixed_signal/cosim/*_cosim_results.json",
               "phase3/mixed_signal/cosim/mixed_signal_results.json"),
        "36": ("reports/phase3/layout_receipts.json",),
    }.get(sid)
    if required_ai_output and not _files(project, *required_ai_output):
        return False, (f"awaiting_signed_judgement: Step {sid} has no AI "
                       "review output to sign")
    if sid == "3":
        if expected_verdict != "PASS":
            return False, "Step3 role acceptance is not a design FAIL judgement"
        roles, why = reset_roles(project)
        return (bool(roles) and "unresolved" not in roles.values(), why)
    sha = evidence_sha256(project, sid)
    receipt = _json(project / "reports/audit/ai_judgements" / f"{sid}.json")
    if (sha and receipt.get("schema") == SCHEMA
            and receipt.get("step_id") == sid
            and receipt.get("evidence_sha256") == sha
            and receipt.get("verdict") == expected_verdict
            and isinstance(receipt.get("signed_by"), str)
            and receipt["signed_by"].strip()
            and isinstance(receipt.get("judgement"), str)
            and receipt["judgement"].strip()):
        return True, f"signed judgement bound to evidence sha256:{sha}"
    return False, (f"awaiting_signed_judgement: Step {sid} requires a {expected_verdict} "
                   f"AI judgement signed over current evidence sha256:{sha}; "
                   f"receipt reports/audit/ai_judgements/{sid}.json")


def pending(project: Path, step_ids: tuple[str, ...]) -> dict[str, str]:
    """Return only hand-offs whose current evidence lacks a matching receipt."""
    return {sid: detail for sid in step_ids
            for credit, detail in (check(project, sid),) if not credit}


def demote_runner_rows(rows: list[dict], awaiting: dict[str, str]) -> None:
    """Keep a runner's named step rows consistent with its aggregate verdict."""
    names = {
        "D1": {"phase1_ingest_render", "phase1_expert_parse_track"},
        "1": {"rtl_gen"},
        "4": {"professional_tb_gen"},
        "A1": {"A1_spec_extract"},
        "A2": {"A2_topology_select"},
        "A9": {"A9_hw_verify"},
    }
    for sid, detail in awaiting.items():
        for row in rows:
            if (row.get("name") in names.get(sid, ())
                    and row.get("status") in ("PASS", "PASS_WITH_WAIVERS")):
                row["program_status"] = row["status"]
                row["program_detail"] = row.get("detail", "")
                row["status"] = "NOT_MEASURED"
                row["reason_class"] = "awaiting_signed_judgement"
                row["detail"] = f"{row.get('detail', '')}; {detail}"


def restore_runner_rows(rows: list[dict]) -> None:
    """A second pass may clear only rows this guard previously demoted."""
    for row in rows:
        if (row.get("status") == "NOT_MEASURED"
                and row.get("reason_class") == "awaiting_signed_judgement"
                and row.get("program_status") in ("PASS", "PASS_WITH_WAIVERS")):
            row["status"] = row.pop("program_status")
            row["detail"] = row.pop("program_detail", row.get("detail", ""))
            row.pop("reason_class", None)


def _intent_files(project: Path) -> list[Path]:
    return _files(project, *DESIGN_INPUT_GLOBS, "phase1/generated_docs/L6*.json",
                  "phase1/generated_docs/L8*.json")


def _reset_context(project: Path):
    import _cdc_netlist as native
    path = project / native.NETLIST_REL
    nl = native.load(path)
    return path, nl, native.require_binding(project, path, nl)


def reset_role_request(project: Path) -> dict:
    """Existing expert fallback, denominated before any role adoption."""
    import _cdc_netlist as native
    try:
        path, nl, binding = _reset_context(project)
        return {"step_id": "3", "scope": "reset-role", "fallback_skill": "rtl-review",
                "receipt": "reports/audit/ai_judgements/3.json",
                "evidence_sha256": evidence_sha256(project, "3"),
                "netlist_sha256": binding["sha256"]["netlist.json"],
                "candidates": native.reset_role_candidates(nl),
                "intent_files": [p.relative_to(project).as_posix() for p in _intent_files(project)]}
    except (native.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        return {"step_id": "3", "scope": "reset-role", "error": str(exc)}


def _role_citations(project: Path, rows, allowed: set[Path]) -> list[str]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("role evidence needs nonempty exact file/line/quote citations")
    quotes = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"file", "line", "quote"}:
            raise ValueError("role citation requires exactly file, line and quote")
        path = (project / str(row["file"])).resolve()
        if path not in allowed or type(row["line"]) is not int or row["line"] < 1 \
                or not isinstance(row["quote"], str) or not row["quote"].strip():
            raise ValueError("role citation is outside the current evidence")
        lines = path.read_text().splitlines()
        if row["line"] > len(lines) or row["quote"] not in lines[row["line"] - 1]:
            raise ValueError("role citation no longer matches current bytes")
        quotes.append(row["quote"])
    return quotes


def _admit_reset_roles(project: Path, receipt: dict, request: dict) -> dict:
    if (receipt.get("schema") != SCHEMA or receipt.get("step_id") != "3"
            or receipt.get("scope") != "reset-role" or receipt.get("verdict") != "PASS"
            or not request.get("evidence_sha256")
            or receipt.get("evidence_sha256") != request["evidence_sha256"]
            or receipt.get("netlist_sha256") != request["netlist_sha256"]
            or not all(isinstance(receipt.get(k), str) and receipt[k].strip()
                       for k in ("signed_by", "judgement"))):
        raise ValueError("missing, foreign or stale Step3 reset-role judgement")
    records = receipt.get("reset_roles")
    candidates = {r["state"]: r for r in request["candidates"]}
    if not isinstance(records, list) or len(records) != len(candidates):
        raise ValueError("reset roles do not cover the intrinsic candidate population")
    intent = {p.resolve() for p in _files(project, *DESIGN_INPUT_GLOBS)}
    _path, _nl, binding = _reset_context(project)
    from formal_property_run import resolve_include_headers
    rtl = [(project / p).resolve() for p in binding["input"]["rtl_files"]]
    source_paths = set(rtl) | {p.resolve() for p in resolve_include_headers(rtl, [project])}
    sources = {(project / row["path"]).resolve()
               for row in binding["input"]["files"]
               if (project / row["path"]).resolve() in source_paths}
    result = {}
    dispositions = {"synchronous_reset", "functional_update", "unresolved"}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("candidate"), dict):
            raise ValueError("role has no exact native candidate identity")
        candidate = row["candidate"]
        state = candidate.get("state")
        role = row.get("role")
        if state in result or json.dumps(candidate, sort_keys=True) != json.dumps(candidates.get(state), sort_keys=True):
            raise ValueError("duplicate, conflicting or foreign state/Q/selector/source identity")
        if role not in dispositions:
            raise ValueError("unknown reset-role disposition")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            raise ValueError("role needs an explicit evidence-based rationale")
        _role_citations(project, row.get("source_context"), sources)
        if role != "unresolved":
            _role_citations(project, row.get("intent"), intent)
            # The trusted expert owns the semantic inference, in any language.
            # This boundary proves current citations, not their interpretation.
        result[state] = role
    return result


def reset_roles(project: Path, nl=None, path: Optional[Path] = None) -> tuple[dict, str]:
    """A signature attributes reviewed bytes; cited intent admits each role."""
    project = Path(project).resolve()
    try:
        request = reset_role_request(project)
        if "error" in request:
            raise ValueError(request["error"])
        if path is not None and hashlib.sha256(path.read_bytes()).hexdigest() != request["netlist_sha256"]:
            raise ValueError("ordinary consumer graph differs from the role request")
        receipt = _json(project / "reports/audit/ai_judgements/3.json")
        roles = _admit_reset_roles(project, receipt, request)
        if "unresolved" in roles.values():
            return roles, "RESET_ROLE_UNRESOLVED: expert could not establish every role"
        return roles, "signed judgement bound to current source/graph and cited reset-role intent"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, "awaiting_signed_judgement: Step 3 reset-role: " + str(exc)


def main(argv=None) -> int:
    """Canonical Step3 request/answer writer; it never decides roles itself."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--step", choices=("3",), required=True)
    parser.add_argument("--answer", type=Path)
    parser.add_argument("--signed-by")
    parser.add_argument("--judgement")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    request = reset_role_request(project)
    if args.answer is None:
        print(json.dumps(request, indent=2))
        return 1 if "error" in request else 0
    try:
        if "error" in request:
            raise ValueError(request["error"])
        answer = json.loads(args.answer.read_text())
        if any(answer.get(key) != request[key]
               for key in ("evidence_sha256", "netlist_sha256")):
            raise ValueError("expert answer belongs to different source/graph evidence")
        receipt = {"schema": SCHEMA, "step_id": "3", "scope": "reset-role", "verdict": "PASS",
                   "evidence_sha256": request["evidence_sha256"],
                   "netlist_sha256": request["netlist_sha256"],
                   "signed_by": args.signed_by, "judgement": args.judgement,
                   "reset_roles": answer["reset_roles"]}
        _admit_reset_roles(project, receipt, request)
        from _atomic_artefact import write_json
        target = project / request["receipt"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            import time
            target.with_name(target.name + f".prior-{time.time_ns()}").write_bytes(target.read_bytes())
        write_json(target, receipt)
        print(json.dumps({"receipt": str(target), "roles": len(receipt["reset_roles"])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("RESET_ROLE_UNRESOLVED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

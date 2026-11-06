"""Source-cited reset-role facts consumed by the native CDC/RDC rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

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


def _intent_files(project: Path) -> list[Path]:
    return _files(project, *DESIGN_INPUT_GLOBS, "phase1/generated_docs/L6*.json",
                  "phase1/generated_docs/L8*.json")


def _reset_context(project: Path, nl=None, path: Optional[Path] = None):
    import _cdc_netlist as native
    path = path or project / native.NETLIST_REL
    return path, nl if nl is not None else native.load(path)


def reset_role_request(project: Path, nl=None, path: Optional[Path] = None) -> dict:
    """The intrinsic native candidate population and source files to explain."""
    import _cdc_netlist as native
    try:
        path, nl = _reset_context(project, nl, path)
        return {"step_id": "3", "scope": "reset-role", "fallback_skill": "rtl-review",
                "facts": "reports/audit/ai_judgements/3.json", "netlist": str(path),
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


def _reset_role_facts(project: Path, facts: dict, request: dict) -> dict:
    if not isinstance(facts, dict):
        raise ValueError("reset-role facts must be an object")
    records = facts.get("reset_roles")
    candidates = {r["state"]: r for r in request["candidates"]}
    if not isinstance(records, list) or len(records) != len(candidates):
        raise ValueError("reset roles do not cover the intrinsic candidate population")
    intent = {p.resolve() for p in _files(project, *DESIGN_INPUT_GLOBS)}
    from formal_property_run import resolve_include_headers
    from _specrtl_common import rtl_source_files
    from _rtl_include_hub import SILICON_SKIP_TOKENS
    rtl = [p.resolve() for p in rtl_source_files(project)
           if not any(token in p.name.lower() for token in SILICON_SKIP_TOKENS)]
    sources = set(rtl) | {p.resolve() for p in resolve_include_headers(rtl, [project])}
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
    """Read source-cited semantic roles; native audits decide the verdict."""
    project = Path(project).resolve()
    try:
        request = reset_role_request(project, nl, path)
        if "error" in request:
            raise ValueError(request["error"])
        facts = _json(project / "reports/audit/ai_judgements/3.json")
        roles = _reset_role_facts(project, facts, request)
        if "unresolved" in roles.values():
            return roles, "RESET_ROLE_UNRESOLVED: expert could not establish every role"
        return roles, "source-cited reset-role semantics"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, "RESET_ROLE_UNRESOLVED: " + str(exc)


def main(argv=None) -> int:
    """Read or write source-cited reset-role facts; native audits judge them."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--step", choices=("3",), required=True)
    parser.add_argument("--answer", type=Path)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    request = reset_role_request(project)
    if args.answer is None:
        print(json.dumps(request, indent=2))
        return 1 if "error" in request else 0
    try:
        if "error" in request:
            raise ValueError(request["error"])
        facts = json.loads(args.answer.read_text())
        _reset_role_facts(project, facts, request)
        from _atomic_artefact import write_json
        target = project / request["facts"]
        write_json(target, {"reset_roles": facts["reset_roles"]})
        print(json.dumps({"facts": str(target), "roles": len(facts["reset_roles"])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("RESET_ROLE_UNRESOLVED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

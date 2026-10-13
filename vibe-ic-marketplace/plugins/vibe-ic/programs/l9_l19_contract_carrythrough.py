#!/usr/bin/env python3
"""Carry design-owned cross-layer contracts into their L9/L19 consumers.

VERDICT SEMANTICS: REPAIRS. This producer never declares a design result PASS;
it only preserves requirements already stated by the design inputs. It is
chip-agnostic: routing is by L-layer role and explicit markdown headings, never
by design, PDK, vendor, port, or cell literals.

This producer reads only the design's prose inputs plus its typed tape-out
declaration. It never reads RTL, a testbench, an oracle, a harness, a golden,
or a reference implementation. Existing consumer fields win; reruns are
idempotent. Missing or denied evidence emits nothing rather than a default.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _atomic_artefact as _aa  # noqa: E402
import _prose_polarity as _polarity  # noqa: E402
import l_doc_generator_stamp as _stamp  # noqa: E402
from l_doc_consumer_contract import (  # noqa: E402
    input_doc_texts,
    project_relative_source,
)

TOOL = "l9_l19_contract_carrythrough"
_LAYER_RE = re.compile(r"(?mi)^\s*layer\s*:\s*(L\d+)\s*$")
_STATUS_RE = re.compile(r"(?mi)^\s*status\s*:\s*([^\n#]+)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def submodule_requirement(text: str, name: str, source: str) -> Dict[str, Any]:
    """Read the obligation on a module declaration, never on its parameters.

    The finite vocabulary is required / optional / conditional. Naming is an
    independent contract: this does not alter ``low_confidence``. A condition
    we cannot type is retained as unresolved, which the native consumer refuses
    to treat as permission to omit a module.
    """
    lines = text.splitlines()
    parents: List[Tuple[int, str]] = []
    from phase1_doc_one_shot_runner import (
        _RE_L9_BULLET_SUBMOD_HEADING, _RE_L9_BULLET_SUBMOD_HEADING_v1_6_313,
        _RE_L9_SUBMOD_NUM_HEADING)
    bullet_context = False
    bullet_seen = False
    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            depth = len(heading.group(1))
            parents = [(d, h) for d, h in parents if d < depth]
            title = re.sub(r"^\d+(?:\.\d+)*\s+", "", heading.group(2))
            declared_name = re.split(r"[（(]", title, 1)[0].strip(" `*")
            matches = declared_name == name and bool(_RE_L9_SUBMOD_NUM_HEADING.match(line))
            bullet_context = bool(_RE_L9_BULLET_SUBMOD_HEADING.search(line)
                                  or _RE_L9_BULLET_SUBMOD_HEADING_v1_6_313.search(line))
            bullet_seen = False
        else:
            bullet = re.match(r"^\s*[-*+]\s+(?:\*\*)?`([^`]+)`(?:\*\*)?(.*)$", line)
            matches = bool(bullet_context and bullet and bullet.group(1) == name)
            title = (bullet.group(2).strip() if matches else "")
            if bullet:
                bullet_seen = True
            elif bullet_seen:
                bullet_context = False
            elif _RE_L9_BULLET_SUBMOD_HEADING.search(line):
                bullet_context = True
        if matches:
            # Only a declaration's leading qualifier owns implementation
            # optionality. ``core (required); optional ECC parameter`` stays
            # required, and a body parameter named optional cannot waive it.
            qualifier = re.search(r"[（(]([^）)]*)[）)]", title)
            q = qualifier.group(1) if qualifier else ""
            condition = re.fullmatch(
                r"(?:only\s+(?:when|if)|僅當|仅当)\s*"
                r"(?:top(?:[_ -]?module)?)\s*=\s*`?([A-Za-z_][\w$]*)`?", q.strip(), re.I)
            role = "required"
            result: Dict[str, Any] = {}
            if condition:
                role = "conditional"
                result["requirement_condition"] = {
                    "field": "top_module", "equals": condition.group(1)}
            elif re.search(r"only\s+(?:when|if)|僅當|仅当|若|\bwhen\b|\bif\b", q, re.I):
                role = "conditional"
                result["requirement_condition"] = {"unresolved": q}
            elif re.fullmatch(r"optional|(?:視\s+Plugin\s+設計)?可選包入|"
                              r"(?:视\s+Plugin\s+设计)?可选包入|可省略", q.strip(), re.I):
                role = "optional"
            elif re.search(r"\brequired\b|mandatory|必含|必要|必須|必须", q, re.I):
                role = "required"
            elif heading and any(re.search(
                    r"\brequired\b|mandatory|必要|必含", h, re.I)
                    for _, h in parents):
                role = "required"
            end = index + 1
            if heading:
                while end < len(lines) and not _HEADING_RE.match(lines[end]):
                    end += 1
            result["implementation_requirement"] = role
            result["requirement_evidence"] = [{
                "source": source, "line": index + 1,
                "evidence": "\n".join(lines[index:end]).strip()}]
            return result
        if heading:
            parents.append((len(heading.group(1)), heading.group(2)))
    return {}


def _generated_docs(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def _layer_of(path: Path, text: str) -> Optional[str]:
    match = _LAYER_RE.search(text)
    if match:
        return match.group(1).upper()
    match = re.match(r"(?i)(L\d+)(?:_|\b)", path.name)
    return match.group(1).upper() if match else None


def _status_of(text: str) -> str:
    match = _STATUS_RE.search(text)
    return match.group(1).strip().lower() if match else ""


def _source_documents(project: Path) -> List[Dict[str, str]]:
    """Return one canonical copy of each layer input.

    Prefer pristine ``input/docs`` over an identical extracted Path-A copy;
    content de-duplication keeps a corpus layout from becoming two facts.
    """
    records = input_doc_texts(project)
    records.sort(key=lambda item: (
        0 if "input/docs" in item[0].as_posix() else 1,
        item[0].as_posix()))
    seen_text: set[str] = set()
    out: List[Dict[str, str]] = []
    for path, text in records:
        if text in seen_text:
            continue
        seen_text.add(text)
        layer = _layer_of(path, text)
        if layer is None:
            continue
        source, outside = project_relative_source(path, project)
        if outside:
            continue
        out.append({"layer": layer, "status": _status_of(text),
                    "source": source, "text": text})
    return out


def _sections(text: str, *, descendants: bool = False) -> List[Tuple[str, str]]:
    """Preserve each heading's body, optionally including its descendants."""
    out: List[Tuple[str, str]] = []
    lines = text.splitlines()
    headings = [(i, len(m.group(1)), m.group(2).strip())
                for i, line in enumerate(lines) if (m := _HEADING_RE.match(line))]
    for pos, (start, depth, heading) in enumerate(headings):
        end = next((i for i, level, _ in headings[pos + 1:]
                    if not descendants or level <= depth), len(lines))
        out.append((heading, "\n".join(lines[start:end]).strip()))
    return out


def _selected(records: Iterable[Dict[str, str]], layers: Iterable[str],
              heading_re: Pattern[str], *, scope_limits: bool = False
              ) -> List[Dict[str, str]]:
    wanted = set(layers)
    out: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for record in records:
        if record["layer"] not in wanted:
            continue
        for heading, text in _sections(record["text"], descendants=scope_limits):
            # An explicit boundary states scope; it is not a denial of every
            # obligation listed below it. Ordinary denied features still drop.
            boundary = scope_limits and bool(re.search(
                r"不在.{0,20}約束|不在.{0,20}约束|out\s+of\s+scope|"
                r"not\s+constrained|自由度|freedom", heading, re.I))
            if not heading_re.search(heading) or (
                    _polarity.is_denied(heading) and not boundary):
                continue
            key = (record["source"], text)
            if key in seen:
                continue
            seen.add(key)
            out.append({"source": record["source"],
                        "heading": heading, "evidence": text})
    return out


def _positive_line(records: Iterable[Dict[str, str]], pattern: Pattern[str]
                   ) -> Optional[Dict[str, str]]:
    for record in records:
        for line_no, line in enumerate(record["text"].splitlines(), 1):
            if pattern.search(line) and not _polarity.is_denied(line):
                return {"source": record["source"], "line": line_no,
                        "evidence": line.strip()}
    return None


def _put_if_absent(target: Dict[str, Any], key: str, value: Any,
                   emitted: List[str], prefix: str) -> None:
    if value in (None, "", [], {}) or key in target:
        return
    if isinstance(value, dict) and not any(value.values()):
        return
    target[key] = value
    emitted.append(f"{prefix}.{key}")


def _l9_contract(records: List[Dict[str, str]]) -> Dict[str, Any]:
    build = _selected(records, ("L7",), re.compile(
        r"declaration\s+requirements?|聲明|声明", re.I))
    external = _selected(records, ("L3",), re.compile(
        r"external\s+interface|port|parameter|reset|boot|"
        r"對外|外部|端口|介面|参数|參數|啟動", re.I))
    architecture = _selected(records, ("L2", "L8"), re.compile(
        r"architecture|functional|system|memory|sram|integration|ISA|"
        r"sub[\s_-]?modules?|hierarchy|decomposition|freedom|"
        r"\bcore\b|\bwrapper\b|\binterface\b|"
        r"架構|功能|系統|組成|記憶體|整合|同步|階層|自由度|"
        r"不在.{0,20}約束|out\s+of\s+scope|not\s+constrained", re.I),
        scope_limits=True)
    reset_boot = _selected(records, ("L2", "L3", "L7"), re.compile(
        r"reset|boot|同步|啟動|启动", re.I))
    isa = _selected(records, ("L2", "L7", "L8"), re.compile(
        r"\bISA\b|instruction|bit[- ]?serial|指令|位元", re.I))
    verification = _selected(records, ("L7", "L8"), re.compile(
        r"verification|functional|reset|boot|驗證|验证|整合契約|"
        r"不在.{0,20}約束|out\s+of\s+scope|not\s+constrained", re.I),
        scope_limits=True)

    not_applicable = []
    role_absence = {
        "L4": "no chip-level command or protocol decoder",
        "L5": "no SW-visible chip registers",
        "L6": "no calibration controller",
    }
    for record in records:
        if (record["layer"] in role_absence and record["status"]
                in {"not-applicable", "not applicable", "n/a"}):
            not_applicable.append({
                "layer": record["layer"], "status": "not-applicable",
                "normalized_absence": role_absence[record["layer"]],
                "source": record["source"], "evidence": record["text"],
            })

    reset_semantics: List[Dict[str, str]] = []
    from _reset_input_semantics import declarations
    seen_reset_semantics = set()
    for record in records:
        for row in declarations(record["text"]):
            if len(row["sync_values"]) != 1 or len(row["polarity_values"]) != 1:
                continue
            normalized = (next(iter(row["sync_values"])) + " " +
                          next(iter(row["polarity_values"])).replace("_", "-"))
            if normalized not in seen_reset_semantics:
                seen_reset_semantics.add(normalized)
                reset_semantics.append({"source": record["source"],
                                        "line": row["line"],
                                        "evidence": row["evidence"],
                                        "normalized": normalized})
    retained = _positive_line(records, re.compile(
        r"SRAM.{0,80}(?:contents?\s+(?:retained|preserved)|內容保留|内容保留)",
        re.I))
    if retained:
        reset_semantics.append({
            **retained,
            "normalized": "SRAM contents retained; SRAM retention required",
        })
    first = _positive_line(records, re.compile(
        r"(?:first|第一).{0,40}(?:instruction|指令)", re.I))
    if first:
        reset_semantics.append({**first, "normalized": "first instruction"})

    values = {
        "build_declaration": build,
        "external_interface": external,
        "architecture": architecture,
        "reset_boot": {"requirements": reset_boot,
                       "normalized_semantics": reset_semantics},
        "isa": isa,
        "applicability": not_applicable,
        "verification": {"requirements": verification,
                         "normalized_reset_semantics": reset_semantics},
    }
    return {key: value for key, value in values.items()
            if value not in (None, "", [], {})
            and not (isinstance(value, dict) and not any(value.values()))}


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _not_determined_paths(node: Any, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, str) and value.strip().upper() == "NOT_DETERMINED":
                out.append(path)
            else:
                out.extend(_not_determined_paths(value, path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(_not_determined_paths(value, f"{prefix}[{index}]"))
    return out


def _numeric(value: Any) -> Optional[float]:
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _display_ns(value: float) -> str:
    return f"{int(value)} ns" if value.is_integer() else f"{value:g} ns"


def _normalized_metric_rows(sections: Iterable[Dict[str, str]]
                            ) -> List[Dict[str, str]]:
    """Normalize markdown metric rows without losing the verbatim evidence.

    A metric label often carries a parenthetical scope between its name and
    comparator (``setup slack(all corners) | >= 0``).  The consumer needs the
    stable metric+bound phrase, while the original row remains the authority.
    """
    out: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for section in sections:
        for line in section.get("evidence", "").splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set("".join(cells)) <= {"-", ":"}:
                continue
            if (cells[0].strip().lower() in
                    {"metric", "metrics", "指標", "指标"}
                    and re.search(r"accept|range|target|要求|區間|区间",
                                  cells[1], re.I)):
                continue
            metric = re.sub(r"\([^)]*\)", "", cells[0]).strip()
            bound = cells[1].replace("≥", ">=").replace("≤", "<=").strip()
            if not metric or not bound:
                continue
            key = (metric.lower(), bound.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"normalized": f"{metric} {bound}",
                        "source": section["source"], "evidence": line.strip()})
    return out


def _io_delay_contract(records: List[Dict[str, str]], l19: dict
                       ) -> Optional[Dict[str, Any]]:
    hit = _positive_line(records, re.compile(
        r"(?:input|output|I/O).{0,80}(?:delay|延遲|延迟).{0,80}"
        r"(\d+(?:\.\d+)?)\s*%|"
        r"(\d+(?:\.\d+)?)\s*%.{0,80}(?:input|output|I/O).{0,80}"
        r"(?:delay|延遲|延迟)", re.I))
    if not hit:
        return None
    # Numbers belong to the matched numeric clause, not an adjacent coverage
    # percentage in the larger evidence scope.
    percents = re.findall(r"(\d+(?:\.\d+)?)\s*%", hit["evidence"])
    # The default and its override/disclosure rule share one declared section.
    # Preserve that scope instead of clipping evidence at the numeric line.
    for section in _selected(records, ("L9",), re.compile(
            r"I/O\s+delay|input.*delay|output.*delay|I/O.*延遲", re.I), scope_limits=True):
        if section["source"] == hit["source"] and hit["evidence"] in section["evidence"]:
            hit = {**hit, "evidence": section["evidence"]}
            break
    if not percents:
        return None
    fraction = float(percents[0])
    fields = l19.get("fields") if isinstance(l19.get("fields"), dict) else {}
    derived = []
    seen: set[Tuple[Optional[str], float]] = set()
    for rec in fields.get("constraint_declarations", []):
        if not isinstance(rec, dict) or rec.get("token") != "CLOCK_PERIOD":
            continue
        period = _numeric(rec.get("value"))
        key = (rec.get("scope"), period or 0.0)
        if period is None or period <= 0 or key in seen:
            continue
        seen.add(key)
        delay = period * fraction / 100.0
        derived.append({"scope": rec.get("scope"),
                        "clock_period_ns": period, "delay_ns": delay,
                        "display": _display_ns(delay),
                        "period_source": rec.get("source")})
    policy: Dict[str, Any] = {}
    if re.search(r"\bmay\s+override\b|可(?:依需要)?\s*override", hit["evidence"], re.I):
        policy["override_allowed"] = True
    if re.search(r"override[^\n]{0,100}(?:must|須|必须)[^\n]{0,100}"
                 r"declaration\.json", hit["evidence"], re.I):
        policy["override_requires_declaration"] = True
    return {"default_fraction_percent": fraction,
            "input_delay": f"{fraction:g}% of selected clock period",
            "output_delay": f"{fraction:g}% of selected clock period",
            "derived_defaults": derived, **hit, **policy}


def _timing_exception_contract(records: List[Dict[str, str]]) -> Optional[dict]:
    """Type an explicit exception/proof policy in its original scope.

    This does not invent an exception or claim that an equivalence proof ran.
    The SDC consumer must obtain actual proof evidence before accepting one.
    """
    for section in _selected(records, ("L9",), re.compile(
            r"SDC|timing.*exception|false.*path|multi.*cycle", re.I),
            scope_limits=True):
        evidence = section["evidence"]
        if not re.search(r"false[ -]?path|multi[ -]?cycle", evidence, re.I):
            continue
        if not re.search(r"L7", evidence, re.I):
            continue
        if not re.search(r"(?:須|必须).{0,40}(?:證明等價|证明等价)|"
                         r"(?:must|required|requires).{0,60}equivalence|"
                         r"only\s+with\s+an?\s+equivalence\s+proof", evidence, re.I):
            continue
        return {"allow_automatic": False, "requires_l7_equivalence": True,
                **section}
    return None


def _l19_contract(project: Path, records: List[Dict[str, str]], l19: dict
                  ) -> Dict[str, Any]:
    pad = _selected(records, ("L3", "L9"), re.compile(
        r"pad\s+(?:placement|configuration)|pad.*配置|physical\s+pad", re.I))
    signoff = _selected(records, ("L1", "L7", "L9"), re.compile(
        r"production|sign[- ]?off|timing verification|physical verification|"
        r"量產|簽核|签核|時序驗證|實體驗證", re.I))
    ppa_sections = _selected(records, ("L7",), re.compile(
        r"quality\s+metrics|baseline|acceptance\s+range|PPA|品質|基準|接受區間",
        re.I))

    declaration = _load_json(
        project / "input" / "submission_template" / "tapeout_declaration.json")
    step_answers = _load_json(project / "input" / "step_0_5ic_answers.json")
    answers = (declaration.get("answers")
               if isinstance(declaration, dict)
               and isinstance(declaration.get("answers"), dict) else {})
    # `macro_*` is the HARDMACRO half of the size pair (vibe-ic#2118): a macro
    # delivery declares its own bounding box under a name that says so, and a
    # carry-through that listed only the `die_*` half would report a hardmacro's
    # geometry contract as empty.
    geometry_keys = ("deliverable", "top_cell", "die_area_um", "core_area_um",
                     "fp_sizing", "die_origin_um", "macro_area_um",
                     "macro_origin_um", "database_unit_um")
    geometry = {key: answers[key] for key in geometry_keys
                if key in answers and not (
                    isinstance(answers[key], str)
                    and answers[key].strip().upper() == "NOT_DETERMINED")}
    unresolved = _not_determined_paths(declaration or {})

    operator: Dict[str, Any] = {}
    if isinstance(step_answers, dict):
        raw_operator = step_answers.get("operator_template")
        if isinstance(raw_operator, dict):
            reason = raw_operator.get("absent_reason")
            if isinstance(reason, str) and reason.strip():
                operator = {
                    "route": "self-tapeout, no operator",
                    "operator_precheck": "not claimed",
                    "absent_reason": reason.strip(),
                    "source": "input/step_0_5ic_answers.json",
                }

    values = {
        "io_delay": _io_delay_contract(records, l19),
        "timing_exceptions": _timing_exception_contract(records),
        "implementation_constraints": _selected(records, ("L9",), re.compile(
            r"fanout|floorplan|utilization|density|power\s+network|PDN|"
            r"SDC|不在.{0,20}約束|out\s+of\s+scope|not\s+constrained", re.I),
            scope_limits=True),
        "pad_order_by_side": {
            "logical_grouping": pad,
            "implementation_details": (
                "NOT_DETERMINED" if any(
                    p.startswith("answers.pad_") for p in unresolved) else None),
        },
        "tapeout_geometry": geometry,
        "operator_template": operator,
        "unresolved": {
            "status": "NOT_DETERMINED" if unresolved else None,
            "count": len(unresolved), "fields": unresolved,
            "source": ("input/submission_template/tapeout_declaration.json"
                       if declaration else None),
        },
        "signoff": signoff,
        "ppa_acceptance": {
            "requirements": ppa_sections,
            "normalized_metrics": _normalized_metric_rows(ppa_sections),
        },
    }
    return {key: value for key, value in values.items()
            if value not in (None, "", [], {})
            and not (isinstance(value, dict) and not any(value.values()))}


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    gd = _generated_docs(project)
    l9_path = gd / "L9_INTEGRATION_SPEC.json"
    l19_path = gd / "L19_CONSTRAINTS_PDK.json"
    missing = [p.name for p in (l9_path, l19_path) if not p.is_file()]
    if missing:
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": f"consumer layer(s) absent: {', '.join(missing)}",
                "emitted": []}
    l9, l19 = _load_json(l9_path), _load_json(l19_path)
    if l9 is None or l19 is None:
        return {"tool": TOOL, "status": "ERROR",
                "reason": "L9 and/or L19 is unreadable", "emitted": []}

    records = _source_documents(project)
    emitted: List[str] = []
    integration = l9.get("integration")
    integration = integration if isinstance(integration, dict) else {}
    for key, value in _l9_contract(records).items():
        _put_if_absent(integration, key, value, emitted, "L9.integration")
    if integration:
        l9["integration"] = integration

    constraints = l19.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    for key, value in _l19_contract(project, records, l19).items():
        _put_if_absent(constraints, key, value, emitted, "L19.constraints")
    if constraints:
        l19["constraints"] = constraints

    if emitted and not dry_run:
        _stamp.dump(l9_path, l9)
        _stamp.dump(l19_path, l19)
    return {"tool": TOOL, "status": "OK", "dry_run": dry_run,
            "input_documents": len(records), "emitted_count": len(emitted),
            "emitted": emitted,
            "written": ([] if dry_run or not emitted else
                        [str(l9_path), str(l19_path)])}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog=TOOL, description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    report = run(project, dry_run=args.dry_run)
    if args.json:
        _aa.write_json(args.json, report)
    status = report.get("status")
    if status == "ERROR":
        print(f"{TOOL}: ERROR — {report.get('reason')}")
        return 1
    if status == "SKIPPED":
        print(f"{TOOL}: SKIPPED — {report.get('reason')}")
        return 0
    print(f"{TOOL}: lifted {report.get('emitted_count', 0)} "
          "design-owned consumer contract field(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

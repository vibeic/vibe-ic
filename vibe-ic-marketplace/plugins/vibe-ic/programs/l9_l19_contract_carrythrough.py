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


def _sections(text: str) -> List[Tuple[str, str]]:
    """Split markdown at every heading, preserving heading plus body."""
    out: List[Tuple[str, str]] = []
    heading = ""
    body: List[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if heading:
                out.append((heading, "\n".join(body).strip()))
            heading = match.group(2).strip()
            body = [line]
        elif heading:
            body.append(line)
    if heading:
        out.append((heading, "\n".join(body).strip()))
    return out


def _selected(records: Iterable[Dict[str, str]], layers: Iterable[str],
              heading_re: Pattern[str]) -> List[Dict[str, str]]:
    wanted = set(layers)
    out: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for record in records:
        if record["layer"] not in wanted:
            continue
        for heading, text in _sections(record["text"]):
            if not heading_re.search(heading) or _polarity.is_denied(heading):
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
        r"架構|功能|系統|組成|記憶體|整合|同步", re.I))
    reset_boot = _selected(records, ("L2", "L3", "L7"), re.compile(
        r"reset|boot|同步|啟動|启动", re.I))
    isa = _selected(records, ("L2", "L7", "L8"), re.compile(
        r"\bISA\b|instruction|bit[- ]?serial|指令|位元", re.I))
    verification = _selected(records, ("L7", "L8"), re.compile(
        r"verification|functional|reset|boot|驗證|验证|整合契約", re.I))

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
    sync = _positive_line(records, re.compile(
        r"(?:synchronous|同步).{0,80}active[- ]?high|"
        r"active[- ]?high.{0,80}(?:synchronous|同步)", re.I))
    if sync:
        reset_semantics.append({**sync,
                                "normalized": "synchronous active-high"})
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
    percents = re.findall(r"(\d+(?:\.\d+)?)\s*%", hit["evidence"])
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
    return {"default_fraction_percent": fraction,
            "input_delay": f"{fraction:g}% of selected clock period",
            "output_delay": f"{fraction:g}% of selected clock period",
            "derived_defaults": derived, **hit}


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
    geometry_keys = ("deliverable", "top_cell", "die_area_um", "core_area_um",
                     "fp_sizing", "die_origin_um", "database_unit_um")
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

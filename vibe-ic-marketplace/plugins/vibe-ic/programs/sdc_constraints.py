"""ORGANIC #554 (a) — shared staged-SDC ground-truth helpers.

Both phase1 (doc ingestion -> L8/L19) and phase3 (PnR/STA SDC
emission) need to read the project's staged ``input/constraints/*.sdc``
and ``input/reference_flow/**/*.sdc`` files for ``create_clock -period
<ns> [get_ports <port>]`` directives. A single shared module keeps the
two consumers from drifting (emitter/checker doctrine, v0.1.49).

Chip-AGNOSTIC: pure standard-SDC syntax, no chip-class literals.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

_PERIOD_RE = re.compile(r"-period\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_PORT_RE = re.compile(r"get_ports\s+\{?\s*([A-Za-z_]\w*)", re.IGNORECASE)
_NAME_RE = re.compile(r"-name\s+\{?\s*([A-Za-z_]\w*)", re.IGNORECASE)

# A real-world SDC (e.g. OpenROAD-flow-scripts `constraint.sdc`) commonly
# uses Tcl variables rather than literals:
#
#   set clk_name      core_clock
#   set clk_port_name clk_i
#   set clk_period    10.0
#   set clk_port      [get_ports $clk_port_name]
#   create_clock -name $clk_name -period $clk_period $clk_port
#
# `_SET_RE` collects `set <var> <value>` assignments; `_VAR_REF_RE`
# substitutes `$var` / `${var}` references (multi-pass, so a variable
# whose value itself references another variable resolves fully)
# before the period/port/name regexes above run.
_SET_RE = re.compile(r"^\s*set\s+(\w+)\s+(.+?)\s*$")
_VAR_REF_RE = re.compile(r"\$\{?(\w+)\}?")
_MAX_SUBST_PASSES = 6


def collect_sdc_files(project: Path) -> List[Path]:
    """Return every staged SDC file in priority order:
    ``input/constraints/*.sdc`` then ``input/reference_flow/**/*.sdc``."""
    files: List[Path] = []
    cdir = project / "input" / "constraints"
    if cdir.is_dir():
        files.extend(sorted(cdir.glob("*.sdc")))
    rdir = project / "input" / "reference_flow"
    if rdir.is_dir():
        files.extend(sorted(rdir.rglob("*.sdc")))
    return files


def _collect_tcl_vars(text: str) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    for line in text.splitlines():
        m = _SET_RE.match(line)
        if m:
            variables[m.group(1)] = m.group(2).strip()
    return variables


def _substitute_vars(text: str, variables: Dict[str, str]) -> str:
    for _ in range(_MAX_SUBST_PASSES):
        def repl(m: "re.Match") -> str:
            return variables.get(m.group(1), m.group(0))
        new_text = _VAR_REF_RE.sub(repl, text)
        if new_text == text:
            return new_text
        text = new_text
    return text


def collect_create_clocks(project: Path) -> List[Dict]:
    """Return every ``create_clock`` directive found in the staged SDC
    files as ``{period_ns, port_name, name, source}``.

    Tcl variables (``set <var> <value>`` assignments earlier in the
    same file) referenced via ``$var`` / ``${var}`` are substituted
    before parsing, so OpenROAD-flow-scripts-style constraint files
    (``-period $clk_period ... [get_ports $clk_port_name]``) resolve
    to their literal values, not just hand-written literal SDCs."""
    out: List[Dict] = []
    for sdc in collect_sdc_files(project):
        try:
            text = sdc.read_text(errors="replace")
        except OSError:
            continue
        variables = _collect_tcl_vars(text)
        for line in text.splitlines():
            if "create_clock" not in line.lower():
                continue
            resolved = _substitute_vars(line, variables) if variables else line
            mp = _PERIOD_RE.search(resolved)
            if not mp:
                continue
            try:
                period_ns = float(mp.group(1))
            except ValueError:
                continue
            mport = _PORT_RE.search(resolved)
            mname = _NAME_RE.search(resolved)
            out.append({
                "period_ns": period_ns,
                "port_name": mport.group(1) if mport else None,
                "name": mname.group(1) if mname else None,
                "source": str(sdc),
            })
    return out


def primary_clock(project: Path) -> Optional[Dict]:
    """Return the ``create_clock`` entry with the smallest period (the
    fastest / primary clock), or ``None`` if no SDC clocks are staged."""
    clocks = collect_create_clocks(project)
    if not clocks:
        return None
    return min(clocks, key=lambda c: c["period_ns"])


def main(argv=None) -> int:
    """CLI smoke-check: print the primary clock JSON for <project_path>.
    Returns 0; prints ``null`` when no staged SDC clocks are found."""
    import argparse
    import json as _json
    import sys

    parser = argparse.ArgumentParser(
        description="Print primary create_clock from staged SDC files.")
    parser.add_argument("project", help="Project root directory")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    clk = primary_clock(Path(args.project))
    print(_json.dumps(clk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

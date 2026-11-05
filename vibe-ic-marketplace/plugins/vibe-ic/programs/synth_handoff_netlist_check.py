#!/usr/bin/env python3
"""Step 14 on the tool path: judge the synthesis HANDOFF NETLIST, not its recipe.

When step 9 runs LibreLane Yosys.Synthesis the recipe is the tool's fixed code
(setundef -> hilomap -> opt_clean -purge), so auditing script text has nothing
to audit. What must still hold at the handoff is a property of the netlist:

* no constant reaches a cell pin or a port as a literal (`1'h0`, `1'b1`,
  `1'bx`...). A literal constant is what `hilomap` exists to remove; OpenROAD
  turns it into `zero_`/`one_` nets and the detailed router fails on them
  (DRT-0305, the fresh-agent v068 run). An x/z literal is an undefined value.
* the resolved configuration names both tie cells (SYNTH_TIEHI_CELL /
  SYNTH_TIELO_CELL), so the recipe had somewhere to map a constant.
* the tie cells it placed are counted, as evidence.

LibreLane's Checker.YosysUnmappedCells / YosysSynthChecks /
NetlistAssignStatements run beside this gate; they do not look at constants.

ENFORCEMENT: blocking — `phase3_one_shot_runner._step_synth_librelane` runs
this gate on the tool's netlist and a nonzero exit fails the step.

chip-AGNOSTIC: the tie-cell names come from the resolved tool config.
Exit: 0 PASS, 1 FAIL, 2 NOT_MEASURED (unreadable input).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402

#: A Verilog sized literal as Yosys `write_verilog` prints a constant.
_LITERAL = r"\d+'[bhdo][0-9a-fA-FxXzZ_?]+"
_ASSIGN_CONST_RE = re.compile(r"^\s*assign\s+(\S+)\s*=\s*(" + _LITERAL + r")\s*;", re.M)
_PIN_CONST_RE = re.compile(r"\.(\w+)\(\s*(" + _LITERAL + r")\s*\)")
_CONST_NET_RE = re.compile(r"\b(zero_|one_)\b")


def constant_connections(netlist: str) -> list[dict[str, str]]:
    """Every literal constant driving a port (assign) or a cell pin."""
    found = [{"kind": "assign", "target": m.group(1), "value": m.group(2)}
             for m in _ASSIGN_CONST_RE.finditer(netlist)]
    found += [{"kind": "pin", "target": m.group(1), "value": m.group(2)}
              for m in _PIN_CONST_RE.finditer(netlist)]
    found += [{"kind": "net", "target": m.group(1), "value": m.group(1)}
              for m in _CONST_NET_RE.finditer(netlist)]
    return found


def _master(cell: Any) -> Optional[str]:
    return str(cell).split("/", 1)[0] if cell else None


def check(netlist: Path, resolved: dict) -> dict:
    text = netlist.read_text(errors="replace")
    findings = []
    tiehi, tielo = _master(resolved.get("SYNTH_TIEHI_CELL")), _master(resolved.get("SYNTH_TIELO_CELL"))
    if not tiehi or not tielo:
        findings.append(f"TIE_CELL_UNDECLARED: SYNTH_TIEHI_CELL={resolved.get('SYNTH_TIEHI_CELL')!r} "
                        f"SYNTH_TIELO_CELL={resolved.get('SYNTH_TIELO_CELL')!r}")
    constants = constant_connections(text)
    undefined = [c for c in constants if re.search(r"[xXzZ?]", c["value"].split("'", 1)[-1])]
    if constants:
        findings.append(f"CONSTANT_NOT_TIED: {len(constants)} literal constant(s) at the handoff "
                        f"(first: {constants[0]['kind']} {constants[0]['target']} = {constants[0]['value']})")
    if undefined:
        findings.append(f"UNDEFINED_CONSTANT: {len(undefined)} x/z literal(s)")
    ties = {name: len(re.findall(r"^\s*" + re.escape(name) + r"\s", text, re.M))
            for name in (tiehi, tielo) if name}
    return {"program": "synth_handoff_netlist_check", "step": "14",
            "verdict": "FAIL" if findings else "PASS", "netlist": str(netlist),
            "tie_cells": ties, "constants": constants[:50],
            "constant_count": len(constants), "findings": findings}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yosys_check_errors(report, resolved: dict) -> int:
    """Use the native warning-block rules, including configured exclusions.

    Source: vibeic/librelane 50567b0576db59ebfe26e5a22bec56f2486f8292,
    librelane/steps/pyosys.py::_parse_yosys_check (source SHA256
    e125208701d12371f54879cb350f480cd7dd3acfcc077375700a93b3190dae73).
    Only native debug/verbose logging is omitted; parsing needs no installed
    LibreLane package or a container launch in a retained-evidence reader.
    """
    errors, current_warning = 0, None
    for line in report:
        if line.startswith("Warning:") or line.startswith("Found and reported"):
            last_warning, current_warning = current_warning, line
            if last_warning is None:
                continue
            cells = re.findall(r"cell\s+\S+\s+\((\S+)\)", last_warning)
            if resolved["SYNTH_ELABORATE_ONLY"] and "but has no driver" in last_warning:
                continue
            if resolved["SYNTH_CHECKS_ALLOW_TRISTATE"] and (
                    "tribuf" in last_warning or any(
                        fnmatch.fnmatch(cell, pattern) for cell in cells
                        for pattern in (resolved["TRISTATE_CELLS"] or []))):
                continue
            errors += 1
        elif re.match(r"^\s+.+$", line) is not None and current_warning is not None:
            current_warning += line
    return errors


def critical_synthesis_checks(folder: Path, resolved: dict) -> dict[str, int]:
    """Count native Yosys warnings in both original CHECK reports."""
    counts = {}
    for name in ("pre_synth_chk.rpt", "chk.rpt"):
        with (folder / "reports" / name).open() as stream:
            counts[name] = _yosys_check_errors(stream, resolved)
    if any(counts.values()):
        raise ValueError(f"native synthesis critical CHECK errors: {counts}")
    return counts




def _project_path_resolver(project: Path, folder: Path, state: dict):
    """Resolve native State paths in the current project and installed PDK."""
    from librelane_contract import project_path
    return lambda value: project_path(project, value)


def _native_synthesis(project: Path, folder: Path, top: str, *, path_resolver=None) -> tuple[Path, dict, dict]:
    """Read the native netlist, configuration, statistics and CHECK reports."""
    import librelane_contract as LC
    cfg = json.loads((folder / 'config.json').read_text())
    state = json.loads((folder / 'state_out.json').read_text())
    resolve_path = path_resolver or (lambda value: LC.project_path(project, value))
    raw = resolve_path(state['nl']).resolve()
    if not raw.is_file():
        raise ValueError('native synthesis netlist is missing')
    if cfg.get('DESIGN_NAME') != top:
        raise ValueError('native synthesis top differs from requested top')
    stat = json.loads((folder / 'reports/stat.json').read_text())
    modules = stat.get('modules')
    module = (modules.get('\\' + top) or modules.get(top)) if isinstance(modules, dict) else None
    if not module or len(modules) != 1 or module.get('num_submodules') != 0:
        raise ValueError('native stat does not establish a flattened top')
    metrics = state.get('metrics', {})
    if metrics.get('design__instance_unmapped__count') != 0 or metrics.get('synthesis__check_error__count') != 0:
        raise ValueError('native synthesis checks did not measure zero errors')
    critical_synthesis_checks(folder, cfg)
    report = check(raw, cfg)
    if report['verdict'] != 'PASS':
        raise ValueError('; '.join(report['findings']))
    return raw, cfg, report


def bound_handoff(project: Path) -> Optional[dict]:
    """Read the selected native synthesis product for downstream consumers."""
    import librelane_contract as LC
    sidecar = project / 'phase2/stage2/synth/synth_inputs.json'
    try:
        doc = json.loads(sidecar.read_text()) if sidecar.is_file() else {}
        binding = doc.get('librelane_synthesis')
        if isinstance(binding, dict) and binding.get('folder'):
            folder = LC.project_path(project, binding['folder'])
        else:
            folders = [path.parent for path in (project / 'phase3/librelane').glob('**/state_out.json')
                       if (path.parent / 'config.json').is_file() and
                       (LC._load(path.parent / 'config.json').get('meta') or {}).get('step') == 'Yosys.Synthesis'
                       and 'attempts' not in path.relative_to(project).parts]
            if not folders:
                return None
            if len(folders) != 1:
                raise ValueError('native synthesis State is ambiguous')
            folder = folders[0]
            binding = {}
        config = json.loads((folder / 'config.json').read_text())
        top = config.get('DESIGN_NAME')
        if not isinstance(top, str) or not top:
            raise ValueError('native synthesis has no design name')
        raw, config, report = _native_synthesis(project, folder, top)
        import librelane_postmap as postmap
        parent = raw
        raw, child_folder = postmap.selected(project, binding, parent, folder)
        if child_folder:
            report = check(raw, config)
            if report['verdict'] != 'PASS':
                raise ValueError('; '.join(report['findings']))
        mapped = LC.project_path(project, binding.get('mapped', str(raw)))
        if not mapped.is_file():
            raise ValueError('mapped synthesis netlist is absent')
        report.update(producer='LibreLane.Yosys.Synthesis', native=str(raw),
                      parent=str(parent), mapped=str(mapped), folder=str(folder),
                      canonical=str(mapped.parent / 'netlist.v'), flattened=True,
                      reason_class='native_synthesis_result')
        return report
    except (LC.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'program': 'synth_handoff_netlist_check', 'step': '14',
                'verdict': 'FAIL', 'reason_class': 'native_synthesis_unreadable',
                'findings': [str(exc)]}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True,
                        help="the synthesis step's resolved config (config.json)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    try:
        resolved = json.loads(args.resolved.read_text())
        report = check(args.netlist, resolved)
    except (OSError, ValueError) as exc:
        report = {"program": "synth_handoff_netlist_check", "verdict": "NOT_MEASURED",
                  "findings": [str(exc)]}
    if args.json:
        write_json(args.json, report)
    print(f"[{report['verdict']}] " + "; ".join(report["findings"]))
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())

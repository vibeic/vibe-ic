#!/usr/bin/env python3
"""dft_post_optimization_scan_survival_check.py — does post-DFT optimization
(Step 12, "resynth / buffering") actually PRESERVE the scan chain Step 11
inserted, or did the netlist it emits quietly lose it?

THE DEFECT THIS CLOSES
-----------------------
Step 12's gate was ``files_exist: [phase2/stage2/synth/post_dft_netlist.v]``
only — satisfied by an empty file, by the PRE-DFT netlist copied over
verbatim, or by a netlist that genuinely carries zero scan cells. Step 13's
LEC (RTL == post-DFT netlist) does NOT catch any of these: scan insertion is
designed to be functionally transparent (scan mode is not exercised in
mission-mode simulation), so a post-DFT netlist with its scan chain silently
dropped is STILL functionally equivalent to the RTL — LEC has nothing to
disagree with. This is a different property than LEC checks, not a
duplicate of it.

WHAT THIS CHECKS, chip- and PDK-AGNOSTIC
-----------------------------------------
Reuses ``fault_atpg_run``'s existing, chip-agnostic DFF-instantiation
detector (the same one ATPG relies on to find the flops it must cut around)
rather than inventing a second, driftable pattern — see
``fault_atpg_run._DFF_INST_RE`` / ``detect_dff_cells``.

FAILs (rc=1) iff any of the three named failure modes is measured:

  1. ``post_dft_netlist.v`` is missing or empty.
  2. ``post_dft_netlist.v`` is byte-identical to the PRE-DFT netlist
     (``phase2/stage2/synth/netlist.v``) — the "pre-DFT netlist copied
     over" substitution named in the flow's own dimension-2 audit.
  3. Step 11's own ``scan_netlist.v`` instantiates at least one DFF-family
     cell (i.e. scan insertion genuinely ran) but ``post_dft_netlist.v``
     instantiates ZERO — the scan chain vanished between Step 11 and
     Step 12.

Deliberately does NOT compare flop COUNTS beyond zero-vs-nonzero: resynthesis
legitimately may retime, balance or otherwise change register count by a
small, benign margin, and a fuzzy percentage threshold would be a second,
driftable definition of "how much loss is too much". The three failure
modes above are the ones actually named as satisfying the old files_exist
gate; this check closes exactly those, no more.

SKIPPED-CONDITION (rc=2), never a silent PASS:
  * ``scan_netlist.v`` (Step 11's own output) is missing — nothing to
    compare survival AGAINST, so failure mode 3 is unmeasurable. This is a
    disclosed skip, not a pass on absence: the caller's condition_files_exist
    on the gate clause is what actually decides whether Step 12 runs this
    check at all (a project with no DFT declares no scan_netlist.v and the
    clause is condition-gated off).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fault_atpg_run import _DFF_INST_RE  # noqa: E402 — the shared, chip-agnostic detector


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _dff_instance_count(netlist_text: str) -> int:
    return sum(1 for _ in _DFF_INST_RE.finditer(netlist_text or ""))


def normalized_netlist_digest(netlist_text: str, *, top: str) -> dict:
    """Normalize one Verilog netlist with Yosys; this is not an admission verdict."""
    import hashlib
    import re
    import shutil
    import subprocess
    import tempfile
    if not isinstance(netlist_text, str) or not netlist_text.strip():
        return {'status': 'NOT_MEASURED', 'reason': 'NETLIST_FORMAT_INVALID'}
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top):
        return {'status': 'NOT_MEASURED', 'reason': 'NETLIST_TOP_INVALID'}
    tool = shutil.which('yosys')
    if not tool:
        return {'status': 'NOT_MEASURED', 'reason': 'NORMALIZER_UNAVAILABLE'}
    try:
        tool_sha = hashlib.sha256(Path(tool).read_bytes()).hexdigest()
        source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        input_sha = hashlib.sha256(netlist_text.encode('utf-8')).hexdigest()
        with tempfile.TemporaryDirectory(prefix='dft-normalize-') as td:
            source = Path(td) / 'source.v'
            target = Path(td) / 'normalized.v'
            source.write_text(netlist_text, encoding='utf-8')
            recipe = f'read_verilog {source}; hierarchy -top {top}; write_verilog -noattr {target}'
            run = subprocess.run([tool, '-Q', '-T', '-p', recipe],
                                 capture_output=True, timeout=60)
            if run.returncode != 0 or not target.is_file() or not target.stat().st_size:
                raise ValueError('Yosys normalization failed')
            normalized = target.read_bytes()
        if (hashlib.sha256(Path(tool).read_bytes()).hexdigest() != tool_sha
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_sha):
            raise ValueError('normalizer changed during execution')
        return {'status': 'MEASURED', 'input_sha256': input_sha,
                'normalized_sha256': hashlib.sha256(normalized).hexdigest(),
                'yosys_sha256': tool_sha, 'source_sha256': source_sha, 'top': top,
                'recipe': ['read_verilog', 'hierarchy -top', 'write_verilog -noattr'],
                'flow109_acceptance': 'NOT_MEASURED'}
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return {'status': 'NOT_MEASURED', 'reason': 'NETLIST_FORMAT_INVALID'}


def compare_normalized_preroute_netlists(points: dict, *, top: str, requires_scan: bool) -> dict:
    """Compare four supplied netlists; callers must separately bind each producer."""
    if type(requires_scan) is not bool:
        return {'status': 'NOT_MEASURED', 'reason': 'SCAN_APPLICABILITY_UNRESOLVED'}
    start = 'D24' if requires_scan else 'D22'
    order = (start, 'D25', 'D26', 'D30')
    if not isinstance(points, dict) or set(points) != set(order):
        return {'status': 'NOT_MEASURED', 'reason': 'CHAIN_POINT_MISSING'}
    evidence = {}
    for point in order:
        record = normalized_netlist_digest(points[point], top=top)
        if record['status'] != 'MEASURED':
            return {'status': 'NOT_MEASURED', 'reason': record['reason'], 'point': point}
        evidence[point] = record
    if len({(v['yosys_sha256'], v['source_sha256']) for v in evidence.values()}) != 1:
        return {'status': 'NOT_MEASURED', 'reason': 'NORMALIZER_IDENTITY_CHANGED'}
    expected = evidence[start]['normalized_sha256']
    mismatch = [point for point in order[1:] if evidence[point]['normalized_sha256'] != expected]
    return {'status': 'FAIL' if mismatch else 'PASS', 'start': start,
            'mismatch': mismatch, 'points': evidence, 'flow109_acceptance': 'NOT_MEASURED'}


def reconcile_scan_cell_list(mapped: str, replaced: str, adopted: str, cells: list, *, top: str) -> dict:
    """Compare a D23 list using complete Yosys parses of all three netlists.

    This is a component check: its caller must bind the D23 native execution
    and all three inputs before using it as Flow109 evidence.
    """
    import hashlib
    import shutil
    import subprocess
    import tempfile
    tool = shutil.which('yosys')
    if not tool or not isinstance(top, str) or not top:
        return {'verdict': 'NOT_MEASURED', 'reason': 'NETLIST_PARSER_UNAVAILABLE'}
    try:
        tool_hash = hashlib.sha256(Path(tool).read_bytes()).hexdigest()
        parsed = []
        with tempfile.TemporaryDirectory(prefix='dft-cell-parse-') as td:
            for index, text in enumerate((mapped, replaced, adopted)):
                if not isinstance(text, str) or not text.strip():
                    raise ValueError('empty netlist')
                source = Path(td) / f'in{index}.v'
                result = Path(td) / f'out{index}.json'
                source.write_text(text)
                cmd = f'read_verilog {source}; write_json {result}'
                run = subprocess.run([tool, '-Q', '-T', '-p', cmd], capture_output=True, timeout=60)
                if run.returncode != 0 or not result.is_file():
                    raise ValueError('Yosys netlist parse failed')
                document = json.loads(result.read_text())
                modules = document.get('modules')
                if not isinstance(modules, dict) or set(modules) != {top}:
                    raise ValueError('expected one selected flat top')
                items = modules[top].get('cells')
                if not isinstance(items, dict) or not items:
                    raise ValueError('native instance population unavailable')
                if any(not isinstance(cell, dict) or not isinstance(cell.get('type'), str)
                       for cell in items.values()):
                    raise ValueError('native cell type unavailable')
                parsed.append({name: cell['type'] for name, cell in items.items()})
        if hashlib.sha256(Path(tool).read_bytes()).hexdigest() != tool_hash:
            raise ValueError('Yosys changed during parsing')
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        return {'verdict': 'NOT_MEASURED', 'reason': 'NATIVE_INSTANCE_POPULATION_UNRESOLVED'}
    before, source, final = parsed
    if set(before) != set(source):
        return {'verdict': 'NOT_MEASURED', 'reason': 'NATIVE_INSTANCE_POPULATION_UNRESOLVED'}
    if not isinstance(cells, list) or not cells:
        return {'verdict': 'NOT_MEASURED', 'reason': 'D23_SCAN_CELL_LIST_MISSING'}
    if any(not isinstance(c, dict) or set(c) != {'instance', 'cell'}
           or not all(isinstance(c[k], str) and c[k] for k in ('instance', 'cell'))
           for c in cells):
        return {'verdict': 'NOT_MEASURED', 'reason': 'D23_SCAN_CELL_LIST_INVALID'}
    claimed = [(c['instance'], c['cell']) for c in cells]
    if len(set(claimed)) != len(claimed) or len({n for n, _ in claimed}) != len(claimed):
        return {'verdict': 'FAIL', 'reason': 'D23_SCAN_CELL_LIST_DUPLICATE'}
    changed = {(name, source[name]) for name in before if before[name] != source[name]}
    if not changed:
        return {'verdict': 'NOT_MEASURED', 'reason': 'NO_SCAN_REPLACEMENTS_OBSERVED'}
    if set(claimed) != changed:
        return {'verdict': 'FAIL', 'reason': 'D23_SCAN_CELL_LIST_MISMATCH',
                'missing': sorted(changed - set(claimed)), 'extra': sorted(set(claimed) - changed)}
    masters = {cell for _, cell in changed}
    adopted_cells = {(name, cell) for name, cell in final.items() if cell in masters}
    if adopted_cells != changed:
        return {'verdict': 'FAIL', 'reason': 'D24_SCAN_CELL_LIST_MISMATCH',
                'missing': sorted(changed - adopted_cells), 'extra': sorted(adopted_cells - changed)}
    return {'verdict': 'PASS', 'reason': 'D23_D24_SCAN_CELL_CONTENT_MATCH',
            'cells': [{'instance': n, 'cell': c} for n, c in sorted(changed)],
            'parser_sha256': tool_hash, 'flow109_acceptance': 'NOT_MEASURED'}


def _missing_dft_ports(project: Path, netlist_text: str) -> list:
    """DFT ports the published scan chain declares, absent from the netlist.

    Failure mode 4 (T92 step 12 harvest): a netlist can keep its flops and
    still lose the chain's access ports. The names are the ones the scan
    producer published (`functional_mode_tieoff` keys and `scan_out_port` in
    reports/phase2/dft/scan_chain.json), never sniffed. Unpublished or absent
    metadata names no port, so nothing is asserted.
    """
    import json as _json
    import re as _re
    meta_path = project / "reports" / "phase2" / "dft" / "scan_chain.json"
    try:
        meta = _json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(meta, dict) or not meta.get("published"):
        return []
    names = list((meta.get("functional_mode_tieoff") or {}).keys())
    if isinstance(meta.get("scan_out_port"), str):
        names.append(meta["scan_out_port"])
    declared = set()
    for m in _re.finditer(r"\b(?:input|output|inout)\b([^;]*);", netlist_text):
        declared.update(_re.findall(r"\\?([A-Za-z_][\w$]*)", m.group(1)))
    return sorted(n for n in names if n not in declared)


def assess(project: Path) -> dict:
    post_dft = project / "phase2" / "stage2" / "synth" / "post_dft_netlist.v"
    pre_dft = project / "phase2" / "stage2" / "synth" / "netlist.v"
    scan = project / "phase2" / "stage2" / "dft" / "scan_netlist.v"

    if not scan.is_file() or not scan.stat().st_size:
        return {"verdict": "SKIPPED-CONDITION", "rc": 2,
                "reason": "phase2/stage2/dft/scan_netlist.v (Step 11's own "
                          "output) is absent — nothing to measure scan-chain "
                          "survival against"}

    post_text = _read(post_dft)
    if not post_dft.is_file() or not post_text.strip():
        return {"verdict": "FAIL", "rc": 1,
                "reason": "phase2/stage2/synth/post_dft_netlist.v is missing "
                          "or empty"}

    pre_text = _read(pre_dft) if pre_dft.is_file() else None
    if pre_text is not None and post_text == pre_text:
        return {"verdict": "FAIL", "rc": 1,
                "reason": "phase2/stage2/synth/post_dft_netlist.v is "
                          "byte-identical to the PRE-DFT netlist "
                          "(phase2/stage2/synth/netlist.v) — the DFT/scan "
                          "insertion step's output was never actually "
                          "carried forward into this file"}

    scan_dffs = _dff_instance_count(_read(scan))
    post_dffs = _dff_instance_count(post_text)

    if scan_dffs > 0 and post_dffs == 0:
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"scan_netlist.v instantiates {scan_dffs} "
                           f"DFF-family cell(s) (scan insertion ran), but "
                           f"post_dft_netlist.v instantiates 0 — the scan "
                           f"chain did not survive post-DFT optimization"),
                "scan_netlist_dff_count": scan_dffs,
                "post_dft_netlist_dff_count": post_dffs}

    missing_ports = _missing_dft_ports(project, post_text)
    if missing_ports:
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"reports/phase2/dft/scan_chain.json publishes DFT "
                           f"port(s) {missing_ports} that post_dft_netlist.v no "
                           f"longer declares — the chain lost its access "
                           f"ports during post-DFT optimization"),
                "missing_dft_ports": missing_ports,
                "scan_netlist_dff_count": scan_dffs,
                "post_dft_netlist_dff_count": post_dffs}

    return {"verdict": "PASS", "rc": 0,
            "reason": (f"post_dft_netlist.v is non-empty, differs from the "
                       f"pre-DFT netlist, and instantiates "
                       f"{post_dffs} DFF-family cell(s) "
                       f"(scan_netlist.v had {scan_dffs})"),
            "scan_netlist_dff_count": scan_dffs,
            "post_dft_netlist_dff_count": post_dffs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    result = assess(project)

    if args.json:
        out = project / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))

    verdict = result["verdict"]
    print(f"verdict: {verdict}")
    print(f"  {result['reason']}")
    if verdict == "SKIPPED-CONDITION":
        print("SKIPPED-CONDITION: " + result["reason"])
    return result["rc"]


if __name__ == "__main__":
    raise SystemExit(main())

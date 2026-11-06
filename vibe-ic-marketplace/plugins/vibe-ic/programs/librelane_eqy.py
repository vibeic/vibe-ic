#!/usr/bin/env python3
"""EQY native script generation and partition report reader."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lec_observable_cone import observable_matchpoint_names

_EQY_STATUSES = ("PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT")


def write_json(path, document):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(document, indent=2) + "\n")


def eqy_script(top: str, rtl: list[Path], netlist: Path, liberty: str,
               *, synthesis: Optional[dict] = None, views: Optional[Path] = None,
               liberty_files: Optional[list[Path]] = None,
               model_verilog: Optional[list[Path]] = None,
               timeout: Optional[int] = None,
               group_all: bool = True) -> str:
    from lec_run import (fsm_encfile_beside_netlist, fsm_signal_names,
                         _equiv_splitnets)
    encoding = fsm_encfile_beside_netlist(str(netlist))
    states = fsm_signal_names(encoding)
    # Without an encoding map, compare FSM behavior rather than raw state codes.
    gold_prep = ([f"hierarchy -top {top}", "proc", "opt -nosdff -nodffe", "fsm"]
                 if states else [])
    split = _equiv_splitnets(encoding, states).replace("splitnets -ports", "splitnets", 1)
    rtl = [*rtl, *(model_verilog or [])]
    if synthesis is not None:
        from rtl_transitive_cone import topological_package_first
        from _rtl_include_hub import macro_headers_first
        rtl = macro_headers_first(topological_package_first(rtl))
    gold = " ".join(str(p) for p in rtl)
    read = f"read_verilog -formal -sv {gold}"
    if synthesis is not None:
        defines = " ".join('-D' + str(d) for d in synthesis.get('VERILOG_DEFINES') or [])
        includes = " ".join('-I ' + str(p) for p in sorted({p.parent for p in rtl}))
        frontend = (f"read_slang --single-unit --top {top}"
                    if synthesis.get('USE_SLANG') else 'read_verilog -sv')
        read = f"{frontend} {defines} {includes} {gold}"
    libraries = [f"read_liberty -ignore_miss_func {liberty}"] if liberty_files is None else [
        f"read_liberty -ignore_miss_func{' -nooverwrite' if model_verilog else ''} {path}"
        for path in liberty_files]
    gate_models = []
    if model_verilog:
        defines = " ".join('-D' + str(d) for d in (synthesis or {}).get('VERILOG_DEFINES') or [])
        includes = " ".join('-I ' + str(p) for p in sorted({p.parent for p in model_verilog}))
        gate_models = [f"read_verilog -formal -sv -overwrite {defines} {includes} "
                       + " ".join(map(str, model_verilog))]
    budget = [f"timeout {timeout}"] if timeout is not None else []
    gold_reads = ([*libraries, read] if (synthesis or {}).get("USE_SLANG")
                  else [read, *(libraries if synthesis is not None else [])])
    return "\n".join([
        "[gold]", *gold_reads, *gold_prep, "",
        "[gate]", *libraries, *gate_models,
        f"read_verilog -formal -sv -icells {netlist}", "",
        "[script]", f"hierarchy -top {top}", "proc",
        *(["[gold]", "opt -nosdff -nodffe", "fsm_detect", "rename -hide a:fsm_encoding=auto", "[script]"]
          if synthesis is not None and not states else []),
        f"prep -top {top} -flatten",
        "memory", *(["[gold]", f"write_json {views}/gold.before-normalization.json",
                      "[gate]", f"write_json {views}/gate.before-normalization.json", "[script]"]
                    if views is not None else []),
        "async2sync", "setundef -init -zero", split.rstrip(),
        observable_matchpoint_names(top).rstrip(), "",
        "[match *]", "gold-nomatch /^_[0-9]+_$/",
        "gate-nomatch /^_[0-9]+_$/", "",
        *(["[collect *]", "group *", ""] if group_all else []),
        "[partition *]", "amend *", "",
        "[strategy sat]", "use sat", "depth 5", *budget, "",
        "[strategy pdr]", "use sby", "engine abc pdr -rfi", *budget, ""])


def partition_status(scratch: Path) -> Optional[dict[str, dict[str, str]]]:
    """{partition: {strategy: status}} from EQY's status files; None if absent."""
    root = scratch / "strategies"
    if not root.is_dir():
        return None
    found: dict[str, dict[str, str]] = {}
    for status in sorted(root.glob("*/*/status")):
        words = status.read_text(errors="replace").split()
        word = words[0] if words else ""
        found.setdefault(status.parent.parent.name, {})[status.parent.name] = (
            word if word in _EQY_STATUSES else "UNREADABLE")
    return found


def xbit_partitions(scratch: Path) -> Optional[list[str]]:
    """Partitions EQY tags `xbits` in partition.list; None if it was not written.

    Such a partition compares signals that are x on the gold side, and EQY's
    miter treats gold x as don't-care — its PASS says nothing (measured: a buf
    in place of an inv behind a resetless flop is `DONE (PASS)`).
    """
    listing = scratch / "partition.list"
    if not listing.is_file():
        return None
    found = []
    for line in listing.read_text(errors="replace").splitlines():
        head, _, _ = line.partition(":")
        words = head.split()
        if len(words) >= 2 and "xbits" in words[2:]:
            found.append(words[1])
    return found


def judge_eqy(folder: Path, output: Path) -> dict:
    scratch = folder / "scratch"
    parts = partition_status(scratch)
    xbits = xbit_partitions(scratch) or []
    listing = scratch / "partition.list"
    lines = listing.read_text(errors="replace").splitlines() if listing.is_file() else []
    heads = [line.partition(":")[0].split() for line in lines if line.strip()]
    declared = [head[1] for head in heads if len(head) >= 2]
    complete = (bool(declared) and len(declared) == len(heads)
                and len(declared) == len(set(declared)) and set(declared) == set(parts or {}))
    proven, failed, unknown = [], [], []
    for name, strategies in (parts or {}).items():
        words = set(strategies.values())
        if "FAIL" in words:
            failed.append(name)
        elif "PASS" in words:
            proven.append(name)
        else:
            unknown.append(name)
    if not parts:
        verdict, why = "NOT_MEASURED", "EQY wrote no partition status (read/partition stage failed)"
    elif failed:
        verdict, why = "FAIL", f"{len(failed)} partition(s) not equivalent: {', '.join(failed[:5])}"
    elif not complete:
        verdict, why = "NOT_MEASURED", "EQY partition declaration/status population is missing or incomplete"
    elif unknown:
        verdict, why = "INCONCLUSIVE", f"{len(unknown)} partition(s) undecided: {', '.join(unknown[:5])}"
    elif xbits:
        verdict, why = "INCONCLUSIVE", (f"EQY_XBITS_VACUOUS: {len(xbits)} partition(s) compare "
                                        f"gold x as don't-care: {', '.join(xbits[:5])}")
    else:
        verdict, why = "PASS", f"all {len(proven)} partition(s) proven"
    report = {"program": "librelane_eqy", "engine": "eqy (LibreLane Yosys.EQY)",
              "verdict": verdict, "explanation": why,
              "compared_points": len(parts or {}), "proven_points": len(proven),
              "non_equivalent_points": failed, "unproven_points": unknown,
              "xbits_partitions": xbits, "partitions": parts, "source": str(folder)}
    write_json(output, report)
    return report


def combine(lec: dict, eqy: dict) -> dict:
    """Keep the conclusive arm. A counterexample in either arm is never outvoted."""
    a = str(lec.get("verdict") or "NOT_MEASURED").upper()
    b = str(eqy.get("verdict") or "NOT_MEASURED").upper()
    if {a, b} == {"PASS", "FAIL"}:
        return {"verdict": "FAIL", "reason": "LEC_ARMS_DISAGREE",
                "detail": f"lec_run={a}, eqy={b}: one arm proves, the other finds a "
                          "counterexample — stop and investigate", "arms": {"lec_run": a, "eqy": b}}
    if "FAIL" in (a, b):
        return {"verdict": "FAIL", "reason": "NOT_EQUIVALENT",
                "selected": "lec_run" if a == "FAIL" else "eqy", "arms": {"lec_run": a, "eqy": b}}
    if a == "PASS":
        return {"verdict": "PASS", "selected": "lec_run",
                "corroborated_by_eqy": b == "PASS", "arms": {"lec_run": a, "eqy": b}}
    if b == "PASS":
        # Arm A undecided (budget, SKIPPED-CONDITION, abort) and did not
        # disprove; EQY proved every partition.
        return {"verdict": "PASS", "selected": "eqy", "arms": {"lec_run": a, "eqy": b}}
    return {"verdict": "INCONCLUSIVE", "reason": "NO_CONCLUSIVE_ARM",
            "arms": {"lec_run": a, "eqy": b}}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="Yosys.EQY step directory")
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    report = judge_eqy(args.folder, args.json)
    print(f"[{report['verdict']}] {report['explanation']}")
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())

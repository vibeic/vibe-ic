#!/usr/bin/env python3
"""mixed_signal_top_lvs_run.py — REAL top-level mixed-signal merge +
LVS (flow-completeness review P1-2; M1 was a PASS-on-presence stub).

What it does (chip-AGNOSTIC; PDK paths derived from --pdk):
  1. MERGE: digital sign-off GDS + every analog hardmacro GDS into
     `phase3/mixed_signal/top_merged.gds` via a KLayout batch script
     (cells coexist in one layout; the digital DEF's macro instances
     resolve against the merged cell names). Skipped when the merged
     GDS already exists.
  2. EXTRACT: Magic `extract all` + `ext2spice lvs` (hierarchy
     preserved — macros stay subckts) on the merged GDS, with the
     PDK's own magicrc.
  3. COMPARE: netgen LVS of the extracted netlist vs the gate-level
     netlist + the hardmacro Verilog stubs (A8 emits them), using the
     PDK's netgen setup. The verdict comes from netgen's REAL compare.
  4. EMIT: `reports/analog/mixed_signal/merge.json` (the M1 gate /
     M4 rollup artifact) with verdict from the LVS result, plus
     `reports/analog/mixed_signal/top_lvs.json` + the netgen report.

Honesty rules: missing tool/tech → SKIP rc 2 with the named gap (the
M1 gate then reports the merge as NOT LVS-verified — it never PASSes
on presence again); a real netgen mismatch → FAIL rc 1.

ENFORCEMENT: advisory
  This is a PRODUCER, not a verdict. It is invoked in M1's
  `advisory_program_exit_zero` slot and dispatched non-blocking from
  `vibe_ic_one_shot_runner` (M1-d4, 2026-07 — before that nothing
  invoked it at all, so M1's declared `top_merged.gds` and the
  `top_lvs.json` its gate demands were never written on any automated
  run and M1 could only come back MISSING). The BLOCKING verdict on
  the merge belongs to `mixed_signal_merge_check`, which reads the
  `top_lvs.json` written here — so nothing is certified without a real
  netgen compare, and an environment failure here does not become a
  second, duplicate blocking FAIL. NOTE: `flow_gate_enforcement_audit`
  reports this as ENFORCED because a runner does invoke it inline; that
  classification is about WIRING, and for a producer inline invocation
  means "it runs", not "it can block".

Usage:
    python3 mixed_signal_top_lvs_run.py <project> --top chip_top
        [--container vibeic-eda] [--pdk sky130A]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import lvs_verdict_tokens as _lvt  # noqa: E402  — #524 shared verdict tokens

TOOLS_IN_CONTAINER = "/foss/tools"
PDKS_IN_CONTAINER = "/foss/pdks"

_KLAYOUT_MERGE_PY = """\
import pya, os
ly = pya.Layout()
ly.read(os.environ["DIGITAL_GDS"])
for g in os.environ["MACRO_GDS"].split(";"):
    if g.strip():
        ly.read(g.strip())
ly.write(os.environ["MERGED_OUT"])
print("KLAYOUT_MERGE_DONE", os.environ["MERGED_OUT"])
"""

_MAGIC_EXT_TCL = """\
crashbackups stop
gds readonly true
gds rescale false
gds read $env(GDS)
load $env(TOP)
select top cell
extract all
ext2spice lvs
ext2spice -o $env(SPICE_OUT)
puts "MAGIC_EXT2SPICE_DONE $env(SPICE_OUT)"
quit -noprompt
"""


def _docker_exec_raw(container, cmd, timeout=600):
    """Simple bounded wall-clock exec (monkeypatch surface for tests) — for
    short probes. Long tool runs use `_docker_exec(..., marker=...)` → the
    progress-stall watchdog."""
    import subprocess
    if container not in ("", "host"):
        # OWN container-side deadline: a host timeout kills only the
        # `docker exec` CLIENT and ORPHANS the tool inside the container
        # (see `_docker_watchdog.wrap_with_container_timeout`).
        import _docker_watchdog as _dw
        full = ["docker", "exec", container, "bash", "-lc",
                _dw.wrap_with_container_timeout(cmd, timeout)]
    else:
        full = ["bash", "-lc", cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller
        return 1, "", str(exc)


def _docker_exec(container, cmd, timeout=600, *, marker=None, log_path=None):
    """marker=None → `_docker_exec_raw` (short probes). marker set → the shared
    progress-stall watchdog (`_docker_watchdog.run_docker_supervised`): a long,
    open-ended run (KLayout merge, Magic ext2spice, netgen LVS — hours on a big
    merged GDS) is killed ONLY on NO forward progress, never on a fixed
    estimate. `marker` is a token already in the tool's argv. chip/tool-AGNOSTIC.
    Still a monkeypatch surface for tests (fakes absorb marker via **_)."""
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    import _docker_watchdog as _dw
    return _dw.run_docker_supervised(
        container, cmd, marker, docker_exec_raw=_docker_exec_raw,
        log_path=log_path)


def _to_container_path(p, container):
    return str(p)


def _tool_ok(container, tool):
    rc, _, _ = _docker_exec(container, f"command -v {tool} >/dev/null 2>&1",
                            timeout=10)
    return rc == 0


def run(project: Path, top: str, container: str, pdk: str) -> dict:
    ms_dir = project / "phase3" / "mixed_signal"
    rpt_dir = project / "reports" / "analog" / "mixed_signal"
    merged = ms_dir / "top_merged.gds"

    # inputs --------------------------------------------------------------
    dig_cands = (sorted((_pl.gds_dir(project)).glob("*.gds"))
                 + sorted(_pl.pnr_dir(project).glob("*.gds")))
    digital_gds = next((g for g in dig_cands if top in g.stem), None) \
        or (dig_cands[0] if dig_cands else None)
    macro_gds = sorted(
        (project / "phase3" / "analog" / "hardmacro").rglob("*.gds"))
    macro_v = sorted(
        (project / "phase3" / "analog" / "hardmacro").rglob("*.v"))
    netlist = _pl.synth_dir(project) / f"{top}_synth.v"
    if not netlist.is_file():
        nl = sorted(_pl.synth_dir(project).glob("*.v"))
        netlist = nl[0] if nl else netlist

    missing_inputs = []
    if digital_gds is None:
        missing_inputs.append("digital GDS")
    if not macro_gds:
        missing_inputs.append("hardmacro GDS (A8)")
    if not netlist.is_file():
        missing_inputs.append("gate netlist")
    if missing_inputs:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "inputs missing: " + ", ".join(missing_inputs)}

    missing_tools = [t for t in ("klayout", "magic", "netgen")
                     if not _tool_ok(container, t)]
    if missing_tools:
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("tools missing in container: "
                           + ", ".join(missing_tools))}
    magicrc = f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/magic/{pdk}.magicrc"
    netgen_setup = (f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/netgen/"
                    f"{pdk}_setup.tcl")
    missing_tech = [p for p in (magicrc, netgen_setup)
                    if _docker_exec(container,
                                    f"test -f {shlex.quote(p)}",
                                    timeout=10)[0] != 0]
    if missing_tech:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "PDK tech missing: " + ", ".join(missing_tech)}

    ms_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)

    # 1) merge ------------------------------------------------------------
    if not merged.is_file():
        merge_py = ms_dir / "klayout_merge.py"
        merge_py.write_text(_KLAYOUT_MERGE_PY)
        env = (f"export DIGITAL_GDS={_to_container_path(digital_gds, container)} "
               f"MACRO_GDS=\"{';'.join(_to_container_path(g, container) for g in macro_gds)}\" "
               f"MERGED_OUT={_to_container_path(merged, container)} && ")
        cmd = (env + f"klayout -b -r "
               f"{_to_container_path(merge_py, container)} 2>&1 | "
               f"tee {_to_container_path(ms_dir, container)}/merge.log")
        rc, out, err = _docker_exec(
            container, cmd, marker=_to_container_path(merge_py, container))
        if not merged.is_file() or merged.stat().st_size == 0:
            return {"verdict": "FAIL", "rc": 1,
                    "reason": (f"KLayout merge produced no top_merged.gds "
                               f"(rc={rc}); see phase3/mixed_signal/merge.log"),
                    "transcript_tail": (out + err)[-600:]}

    # 2) extract ----------------------------------------------------------
    spice_out = ms_dir / f"{top}_merged_extracted.sp"
    tcl = ms_dir / "ext2spice_merged.tcl"
    tcl.write_text(_MAGIC_EXT_TCL)
    cmd = (f"export GDS={_to_container_path(merged, container)} TOP={top} "
           f"SPICE_OUT={_to_container_path(spice_out, container)} && "
           f"cd {_to_container_path(ms_dir, container)} && "
           f"magic -dnull -noconsole -rcfile {shlex.quote(magicrc)} "
           f"{_to_container_path(tcl, container)} 2>&1 | "
           f"tee {_to_container_path(ms_dir, container)}/ext2spice_merged.log")
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(tcl, container))
    if not spice_out.is_file() or spice_out.stat().st_size == 0:
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"Magic ext2spice on the MERGED GDS produced no "
                           f"netlist (rc={rc})"),
                "transcript_tail": (out + err)[-600:]}
    lay_top = top
    sub_txt = spice_out.read_text(errors="replace")
    if re.search(rf"^\.subckt\s+{re.escape(top)}_flat\b", sub_txt,
                 re.IGNORECASE | re.MULTILINE):
        lay_top = f"{top}_flat"

    # 3) netgen LVS — schematic side = gate netlist + hardmacro .v stubs
    lvs_rpt = rpt_dir / "top_lvs.rpt"
    sch_files = " ".join(
        _to_container_path(f, container) for f in [netlist] + macro_v)
    cmd = (f"export PATH={TOOLS_IN_CONTAINER}/netgen/bin:"
           f"{TOOLS_IN_CONTAINER}/bin:$PATH && "
           f"netgen -batch lvs "
           f"\"{_to_container_path(spice_out, container)} {lay_top}\" "
           f"\"{sch_files} {top}\" {shlex.quote(netgen_setup)} "
           f"{_to_container_path(lvs_rpt, container)}")
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(spice_out, container))
    blob = (out or "") + "\n" + (err or "") + "\n" + (
        lvs_rpt.read_text(errors="replace") if lvs_rpt.is_file() else "")
    # #524 — shared verdict classifier (adds 'failed pin matching', the netgen
    # property-error terminal FAIL, 失配 and the Final-result truncation guard,
    # all missing from the old inline copy) so this site can never drift from
    # the Step-31 gate again.
    lvs_pass = _lvt.classify(blob) == "MATCH"

    # 4) emit M1/M4 artifacts ----------------------------------------------
    top_lvs = {
        "program": "mixed_signal_top_lvs_run", "version": "1.0.0",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "layout": str(merged.relative_to(project)),
        "layout_top": lay_top,
        "schematic": [str(netlist.relative_to(project))]
                     + [str(v.relative_to(project)) for v in macro_v],
        "extracted_netlist": str(spice_out.relative_to(project)),
        "lvs_report": str(lvs_rpt.relative_to(project)),
        "tool": "magic ext2spice + netgen (PDK setup)",
    }
    (rpt_dir / "top_lvs.json").write_text(
        json.dumps(top_lvs, indent=2) + "\n")
    (rpt_dir / "merge.json").write_text(json.dumps({
        "gate": "mixed_signal_merge",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "merged_gds": str(merged.relative_to(project)),
        "macros_merged": [str(g.relative_to(project)) for g in macro_gds],
        "top_lvs": top_lvs["verdict"],
        "note": ("top-level merged-GDS LVS executed (Magic extraction + "
                 "netgen vs gate netlist + hardmacro stubs) — the merge "
                 "claim is LVS-substantiated, not presence-only"),
    }, indent=2) + "\n")

    if lvs_pass:
        return {"verdict": "PASS", "rc": 0, **top_lvs}
    return {"verdict": "FAIL", "rc": 1,
            "reason": ("netgen top-level LVS did not match — real compare "
                       "ran on the merged GDS; design/extraction defect"),
            **top_lvs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--top", default="chip_top")
    ap.add_argument("--container", default="vibeic-eda")
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    rep = run(args.project.resolve(), args.top, args.container, args.pdk)
    rc = rep.pop("rc")
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())

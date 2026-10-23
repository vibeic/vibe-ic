#!/usr/bin/env python3
"""sim_activity_dump.py — a DUT-scoped VCD for vector power, with its scope.

Step 4 simulates the design; Step 33 wants the switching activity of that
simulation. OpenSTA's `read_vcd` needs to be told WHICH VCD scope is the linked
top: MEASURED in the released image (OpenSTA 3.1.0) on a routed netlist with a
testbench VCD, `read_vcd tb.vcd` prints `Annotated 0 pin activities.`,
`read_vcd -scope <tb>/<wrong>` prints the same, and `read_vcd -scope <tb>/<dut>`
annotates the DUT's pins. The deprecated `read_power_activities -vcd` that the
power deck used raises `default is not a mode object` and annotates nothing at
all. So the scope is part of the artefact, not a guess made later: this program
writes the VCD and a manifest naming the scope it verified in the VCD header.

It adds a dump module as a second simulation top (`$dumpvars(0, <tb>.<inst>)`),
so the testbench source is never edited. The dump file is named relative to
the run directory, so the same deck works when the simulator runs in a
container that mounts the tree elsewhere. The testbench is the first one that
instantiates the design top; its instance name comes from the testbench text.

Manifest `activity.json`: vcd, scope (`<tb_top>/<inst>`), dut_module, tb,
vcd_sha256, scope_verified. Exit 0 written; 1 simulated but the VCD is empty or
does not carry the scope; 2 nothing to dump (no testbench instantiates the top).
chip-AGNOSTIC: module/instance names come from the design's own sources.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402

MANIFEST = "activity.json"
DUMP_TOP = "vibeic_vcd_dump"
_MODULE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)", re.M)
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def dut_instance(tb_text: str, dut_module: str) -> Optional[Tuple[str, str]]:
    """(tb_top, instance) when the testbench's first module instantiates the DUT."""
    text = _COMMENTS.sub("", tb_text)
    top = _MODULE.search(text)
    if not top:
        return None
    inst = re.search(r"\b" + re.escape(dut_module)
                     + r"\s*(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
                     r"([A-Za-z_][A-Za-z0-9_$]*)\s*\(", text[top.end():])
    return (top.group(1), inst.group(1)) if inst else None


def module_ports(path: Path, module: str) -> List[Dict[str, Any]]:
    """Read a simple adopted-netlist top interface without changing its bytes."""
    text = _COMMENTS.sub("", Path(path).read_text(errors="replace"))
    found = re.search(r"\bmodule\s+" + re.escape(module)
                      + r"\s*\((.*?)\)\s*;(.*?)\bendmodule\b", text, re.S)
    if not found:
        raise ValueError(f"module {module} not found in {path}")
    ordered = [name.strip() for name in found.group(1).split(",") if name.strip()]
    declared: Dict[str, Dict[str, Any]] = {}
    for match in re.finditer(
            r"(?m)(?:^|(?<=;))\s*(input|output|inout)\s+"
            r"(?:(?:wire|reg|logic)\s+)?(?:signed\s+)?(\[[^\]]+\]\s*)?([^;]+);",
            found.group(2)):
        direction, packed, names = match.groups()
        width = 1
        if packed:
            bounds = re.fullmatch(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]\s*", packed)
            if not bounds:
                raise ValueError(f"nonconstant port width in {module}: {packed}")
            width = abs(int(bounds[1]) - int(bounds[2])) + 1
        for name in names.split(","):
            name = name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
                raise ValueError(f"unsupported port declaration in {module}: {name}")
            declared[name] = {"name": name, "direction": direction,
                              "width": width, "packed": packed.strip() if packed else ""}
    if not ordered or set(ordered) != set(declared):
        raise ValueError(f"incomplete port declarations for {module}")
    return [declared[name] for name in ordered]


def _logical_wrapper(path: Path, logical: str, adopted: str,
                     ports: Sequence[Dict[str, Any]]) -> None:
    lines = [f"module {logical} ({', '.join(p['name'] for p in ports)});"]
    for port in ports:
        packed = (port["packed"] + " ") if port["packed"] else ""
        lines.append(f"  {port['direction']} {packed}{port['name']};")
    links = ", ".join(f".{p['name']}({p['name']})" for p in ports)
    lines += [f"  {adopted} vibeic_adopted ({links});", "endmodule"]
    path.write_text("\n".join(lines) + "\n")


def _settled_testbench(source: Path, destination: Path, clock: str,
                       sample_offset_ns: float) -> Dict[str, Any]:
    """Stage a generated oracle with its sample point moved to SDC authority."""
    text = source.read_text()
    if 'VIBEIC_TB_ORACLE: GENERATED' not in text:
        raise ValueError('GLS sample adjustment requires a generated oracle')
    pattern = re.compile(r'(@\(posedge\s+' + re.escape(clock)
                         + r'\)\s*;\s*)#([0-9]+(?:\.[0-9]+)?)\s*;')
    offsets = [float(match[2]) for match in pattern.finditer(text)]
    if not offsets or len(set(offsets)) != 1:
        raise ValueError('generated oracle has no unique positive-edge sample offset')
    if sample_offset_ns <= offsets[0]:
        raise ValueError('GLS sample authority must follow the original oracle sample')
    value = format(sample_offset_ns, '.12g')
    staged, count = pattern.subn(lambda match: match[1] + '#' + value + ';', text)
    destination.write_text(staged)
    return {'original': str(source), 'staged': str(destination), 'clock': clock,
            'original_sample_offset_ns': offsets[0],
            'gls_sample_offset_ns': sample_offset_ns, 'adjusted_sites': count,
            'original_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'staged_sha256': hashlib.sha256(staged.encode()).hexdigest()}


def vcd_scopes(vcd: Path) -> List[str]:
    """Every `a/b/c` scope path declared in the VCD header."""
    stack: List[str] = []
    found: List[str] = []
    with vcd.open("r", errors="replace") as fh:
        for line in fh:
            if line.startswith("$enddefinitions"):
                break
            words = line.split()
            if len(words) >= 3 and words[0] == "$scope":
                stack.append(words[2])
                found.append("/".join(stack))
            elif words[:1] == ["$upscope"] and stack:
                stack.pop()
    return found


def _local(argv: Sequence[str], cwd: str) -> Tuple[int, str, str]:
    r = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def dump(rtl: Sequence[str], tbs: Sequence[str], dut_module: str,
         out_dir: Path,
         exec_fn: Optional[Callable[[Sequence[str], str],
                                    Tuple[int, str, str]]] = None,
         *, testbench_dut_module: Optional[str] = None,
         sample_clock: Optional[str] = None,
         sample_offset_ns: Optional[float] = None
         ) -> Dict[str, Any]:
    """Simulate the first testbench that instantiates `dut_module`, dumping it."""
    exec_fn = exec_fn or _local
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen = None
    logical_module = testbench_dut_module or dut_module
    for tb in tbs:
        try:
            found = dut_instance(Path(tb).read_text(errors="replace"), logical_module)
        except OSError:
            continue
        if found:
            chosen = (Path(tb), *found)
            break
    if chosen is None:
        return {"status": "NOT_APPLICABLE",
                "reason": f"no testbench instantiates {logical_module}"}
    tb, tb_top, inst = chosen
    driver_adjustment = None
    if sample_clock is not None or sample_offset_ns is not None:
        if sample_clock is None or sample_offset_ns is None:
            raise ValueError('sample clock and offset must be supplied together')
        staged = out_dir / f"{tb.stem}.gls-driver.v"
        driver_adjustment = _settled_testbench(
            tb, staged, sample_clock, float(sample_offset_ns))
        tb = staged
    vcd = out_dir / f"{tb.stem}.vcd"
    vcd.unlink(missing_ok=True)
    dumper = out_dir / f"{DUMP_TOP}.v"
    simulation_rtl = list(map(str, rtl))
    mapping = None
    dump_scope = f"{tb_top}.{inst}"
    if logical_module != dut_module:
        ports = module_ports(Path(rtl[0]), dut_module)
        wrapper = out_dir / "vibeic_logical_to_adopted.v"
        _logical_wrapper(wrapper, logical_module, dut_module, ports)
        simulation_rtl.append(str(wrapper))
        dump_scope += ".vibeic_adopted"
        mapping = {"logical_module": logical_module, "adopted_module": dut_module,
                   "wrapper": str(wrapper), "ports": ports}
    dumper.write_text(f"module {DUMP_TOP};\n  initial begin\n"
                      f"    $dumpfile(\"{vcd.name}\");\n"
                      f"    $dumpvars(0, {dump_scope});\n  end\nendmodule\n")
    vvp = out_dir / f"{tb.stem}.vvp"
    dirs: List[str] = []
    for d in [tb.parent] + [Path(f).parent for f in rtl]:
        if str(d) not in dirs:
            dirs.append(str(d))
    rc, out, err = exec_fn(["iverilog", "-g2012", "-o", str(vvp),
                            "-s", tb_top, "-s", DUMP_TOP,
                            *[f"-I{d}" for d in dirs],
                            str(tb), *simulation_rtl, str(dumper)],
                           str(out_dir))
    if rc != 0:
        return {"status": "FAIL", "reason": f"iverilog rc={rc}: {err[-400:]}"}
    rc, out, err = exec_fn(["vvp", "-n", str(vvp)], str(out_dir))
    scope = dump_scope.replace(".", "/")
    if not vcd.is_file() or vcd.stat().st_size == 0:
        return {"status": "FAIL", "reason": f"vvp rc={rc} wrote no VCD at {vcd}"}
    verified = scope in vcd_scopes(vcd)
    manifest = {"status": "PASS" if verified else "FAIL",
                "vcd": str(vcd), "scope": scope, "dut_module": dut_module,
                "tb": str(tb), "vvp_rc": rc, "scope_verified": verified,
                "vcd_sha256": hashlib.sha256(vcd.read_bytes()).hexdigest()}
    if mapping:
        manifest["logical_to_adopted_mapping"] = mapping
    if driver_adjustment:
        manifest["driver_adjustment"] = driver_adjustment
    if not verified:
        manifest["reason"] = f"the VCD header declares no scope {scope}"
    write_json(out_dir / MANIFEST, manifest)
    return manifest


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rtl", nargs="+", required=True)
    ap.add_argument("--tb", nargs="+", required=True)
    ap.add_argument("--top", required=True, help="design top module")
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    result = dump(args.rtl, args.tb, args.top, args.out_dir)
    print(f"[sim_activity_dump] {result['status']}: "
          + str(result.get("reason") or result.get("scope")))
    return {"PASS": 0, "NOT_APPLICABLE": 2}.get(result["status"], 1)


if __name__ == "__main__":
    sys.exit(main())

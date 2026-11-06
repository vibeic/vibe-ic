"""Native CVC electrical screen over the selected netlist and extracted SPICE."""
from __future__ import annotations

import vibeic_temp as _vtmp

import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Dict, Optional

import _path_layout as _pl
from _atomic_artefact import write_json
import librelane_contract

REQUIRED_MANUAL = {"ESD protection presence", "io_supply_pad_sufficiency",
                   "Latch-up / well-tap (spacing + device-physics)"}

_CVC_COUNT_RE = re.compile(r"^CVC:\s+([^:]+):\s+(\d+)\s*$", re.M)


def _parse_native_cvc_report(text: str) -> Dict[str, Any]:
    """Grade the completed report; cvc_rv's process status is not a verdict."""
    text = text or ""
    population = re.search(
        r"CVC:\s+(\d+)\(\d+\) instances,\s+(\d+)\(\d+\) nets,\s+"
        r"(\d+)\(\d+\) devices\.", text)
    counts = {name.strip(): int(value)
              for name, value in _CVC_COUNT_RE.findall(text)}
    parsed = {
        "completed": "CVC: End:" in text,
        "instances": int(population.group(1)) if population else None,
        "nets": int(population.group(2)) if population else None,
        "devices": int(population.group(3)) if population else None,
        "counts": counts,
    }
    if not parsed["completed"]:
        return {**parsed, "result": "INCOMPLETE",
                "note": "cvc_rv did not emit CVC: End; rc is not completion"}
    if not population or any(parsed[name] <= 0
                             for name in ("instances", "nets", "devices")):
        return {**parsed, "result": "INCOMPLETE",
                "note": "completed CVC report has no non-empty design population"}
    if counts.get("Total") is None:
        return {**parsed, "result": "INCOMPLETE",
                "note": "completed CVC report has no Total count"}
    total = counts["Total"]
    return {**parsed, "result": "PASS" if total == 0 else "FAIL",
            "note": f"native cvc_rv completed with {total} electrical error(s)"}


def _native_cvc_category(project: Path, top: str, pdk: Any,
                         image: Optional[str], *, extracted_netlist: Optional[Path] = None,
                         adopted_netlist: Optional[Path] = None, pdk_dir: Optional[str] = None,
                         library: Optional[str] = None, power_nets=None,
                         ground_nets=None) -> Dict[str, Any]:
    """Run the selected PDK CVC recipe and read its native error counts."""
    base = {"category": "Native CVC electrical rules", "status": "AUTOMATED",
            "tool": "cvc_rv + PDK-declared libs.tech/librelane/cvc"}
    if not image:
        return {**base, "result": "INCOMPLETE",
                "note": "selected native image absent"}
    pdk_dir = pdk_dir or getattr(pdk, "pdk_path", None)
    library = library or getattr(pdk, "std_cell_library", None)
    if power_nets is None or ground_nets is None:
        power_nets = getattr(pdk, "power_nets", [])
        ground_nets = getattr(pdk, "ground_nets", [])
    extracted_dir = _pl.extracted_dir(project)
    extracted = extracted_netlist or next((path for pattern in ("*.spice", "*.cir", "*.sp", "*_pex.v")
                      for path in sorted(extracted_dir.glob(pattern))
                      if path.is_file()), None)
    adopted = adopted_netlist or _pl.pnr_dir(project) / f"{top}_pnr.v"
    if (not pdk_dir or not library or extracted is None or not adopted.is_file()
            or len(power_nets) != 1 or len(ground_nets) != 1):
        return {**base, "result": "INCOMPLETE",
                "note": "PDK CVC recipe, final netlists, or unique supply pair absent"}
    cvc_dir = f"{pdk_dir}/libs.tech/librelane/cvc"
    cell_cdl = f"{pdk_dir}/libs.ref/{library}/cdl/{library}.cdl"
    out = _pl.reports_phase3_dir(project) / "cvc_native"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "report.rpt"
    receipt_path = out / "result.json"
    shell = f"""set -eu
cvc={shlex.quote(cvc_dir)}
out={shlex.quote(str(out))}
test -r "$cvc/cvcrc" -a -r "$cvc/models" -a -r "$cvc/power.awk" -a -r "$cvc/cdl.awk"
test -r {shlex.quote(cell_cdl)}
awk -f "$cvc/cdl.awk" {shlex.quote(str(extracted))} > "$out/extracted-clean.cdl"
awk '1' "$out/extracted-clean.cdl" {shlex.quote(cell_cdl)} > "$out/design.cdl"
awk -v vdd={shlex.quote(next(iter(power_nets)))} -v gnd={shlex.quote(next(iter(ground_nets)))} \\
  -f "$cvc/power.awk" {shlex.quote(str(adopted))} > "$out/top.power"
sed -e "s|\\$CVC_SCRIPTS_DIR/models|$cvc/models|" \\
    -e "s|\\$DESIGN_NAME|{shlex.quote(top)}|g" \\
    -e "s|\\$signoff_tmpfiles/{shlex.quote(top)}.cdl|$out/design.cdl|" \\
    -e "s|\\$signoff_tmpfiles/\\$CVC_TOP.power|$out/top.power|" \\
    -e "s|\\$signoff_reports/\\$CVC_TOP.rpt|$out/report.rpt|" \\
    "$cvc/cvcrc" > "$out/cvcrc"
cd "$out"
cvc_rv cvcrc > cvc.stdout 2> cvc.stderr
"""
    import _docker_memory as _dmem
    import librelane_contract as _ll
    network, command = _ll.native_tool_command(image, ["bash", "-lc", shell])
    argv = ["docker", "run", *_vtmp.docker_mounts(), *_dmem.docker_memory_flags(
            {"VIBEIC_DOCKER_MEMORY": "16g"}), "--rm", "--network", network,
            "--cpus", "4",
            "-v", f"{Path(project).resolve()}:{Path(project).resolve()}",
            "-v", f"{Path(pdk_dir).resolve()}:{Path(pdk_dir).resolve()}:ro",
            image, "--skip", *command]
    # A fixed output name is part of the Step-28 contract, so invalidate both
    # prior authority files before this invocation.  cvc_rv can return without
    # touching its report; existence after launch must therefore mean THIS
    # launch wrote it, never that an older PASS survived.
    report.unlink(missing_ok=True)
    receipt_path.unlink(missing_ok=True)
    try:
        import _container_exec
        if _container_exec.no_container_route():
            proc = subprocess.run(['bash', '-lc', shell], capture_output=True, text=True)
            (out / 'docker.log').write_text(proc.stdout + proc.stderr)
        else:
            proc = _ll.run_container(argv, supervised=True, log=out / "docker.log")
    except Exception as exc:
        return {**base, "result": "INCOMPLETE",
                "note": f"native CVC launch failed: {exc}"}
    if proc.returncode != 0:
        return {**base, "result": "INCOMPLETE", "native_rc": proc.returncode,
                "note": "native CVC invocation failed; report is not evidence"}
    if not report.is_file():
        return {**base, "result": "INCOMPLETE", "native_rc": proc.returncode,
                "note": "cvc_rv wrote no report"}
    parsed = _parse_native_cvc_report(report.read_text(errors="replace"))
    result = {**base, **parsed, "native_rc": proc.returncode,
              "evidence": str(report)}
    write_json(receipt_path, result)
    return result


def execute(project, context):
    project = Path(project).resolve()
    state = context.get("state") or {}
    config = context.get("config") or {}
    netlist = state.get("nl") or context.get("netlist")
    extracted = state.get("spice") or context.get("extracted_netlist")
    pdk, library = config.get("PDK"), config.get("STD_CELL_LIBRARY")
    root = config.get("PDK_ROOT")
    top = config.get("DESIGN_NAME") or context.get("top")
    if not all((netlist, extracted, pdk, library, root, top)):
        return {"component_status": "NOT_MEASURED", "native_started": False,
                "reason": "Native netlist, extracted SPICE, top or PDK configuration is absent.",
                "manual_review_pending": sorted(REQUIRED_MANUAL)}
    image = context.get("image") or librelane_contract.resolve_image(project)
    native = _native_cvc_category(project, top, None, image,
        adopted_netlist=Path(netlist), extracted_netlist=Path(extracted),
        pdk_dir=str(Path(root) / pdk), library=library,
        power_nets=config.get("VDD_NETS", []), ground_nets=config.get("GND_NETS", []))
    status = native["result"] if native["result"] in {"PASS", "FAIL"} else "NOT_MEASURED"
    report = {"component_status": status, "native_cvc": native,
              "manual_review_pending": sorted(REQUIRED_MANUAL),
              "scope": "CVC electrical rules; ESD and substrate/latch-up device physics remain unmeasured."}
    write_json(project / "reports/native_tools/final_perc.json", report)
    return report

#!/usr/bin/env python3
"""Step 1: every elaborated catalog-IP instance carries its synth-safe values.

ENFORCEMENT: blocking — ``design_one_shot_runner.step_catalog_synth_safe_params``
runs it at step 1, right after the RTL is staged, and a non-zero exit is that
step's FAIL (F28). The step-1 ``program_exit_zero`` clause re-runs it in
flow_compliance_check.

A catalog manifest may declare ``synth_safe_params`` (serv: ``sim=0``, #492).
With the unsafe value Yosys aborts synthesis, or elaborates a simulation-only
block. The catalog-glue author is told to pin the value at the instantiation;
until now nothing checked that it did.

The judge is Yosys, not a regex. ``read_verilog -sv`` (LibreLane's front end
when ``USE_SLANG`` is off), then ``hierarchy -check -top <L9 top>`` and
``write_json``. After ``hierarchy`` each module that synthesis would reach
exists once per distinct parameter set, and its ``parameter_default_values``
are the values that instance really gets -- whether they came from the glue,
an intermediate wrapper or the module's own default. A module no path
reaches is not in the netlist and is not judged.

A module belongs to a pulled IP when its ``src`` names one of the files
``ip_catalog_pull`` copied for that IP. ``read_slang`` is not used: it
flattens the design and writes no per-module parameter values (measured on
the 0.3.79 image).

LibreLane's ``SYNTH_PARAMETERS`` reaches only the top module (``chparam
-set <p> <v> <top>``). When the catalogued IP is itself the top,
``librelane_contract.emit_synthesis_config`` pins the value there; this gate
still judges the RTL as the direct synthesis path elaborates it.

APPLICABILITY COMES FROM THE DESIGN'S DECLARATION (F9, the v1.25.0 rule): the
catalog IPs the input docs name as this design's own reuse,
``ip_catalog_query.declared_catalog_reuse`` -- the same reading that hands
``design_one_shot_runner.step_rtl_gen`` to ``catalog-glue-author``. The pull
record (``plugin_output/declaration.json``, which the flow itself writes) may
only ADD an IP to the judged set; it never makes the gate NOT_APPLICABLE. A
declaration that is missing or unreadable is refused: unread is not empty.

A DECLARED IP MUST BE REACHED (F28, F28b). A catalog IP the input declares as
its reuse, of which no module survives ``hierarchy -top``, is a spec/RTL
inconsistency: FAIL with ``CATALOG_REUSE_DECLARED_NOT_INSTANTIATED``, whether or
not its manifest declares ``synth_safe_params``. It used to PASS with zero
judged rows (an empty denominator), or stand down as NOT_APPLICABLE when the IP
declared no parameter. An IP that only the pull record names is not held to
this: the flow copied it, the design never said it would use it.

Verdicts: PASS (rc 0), FAIL (rc 1), NOT_APPLICABLE (rc 0, ``reason_class``
DESIGN_DECLARED_NA: the design declares no catalog IP, and no pulled IP
declares a synth-safe parameter), NOT_MEASURED (rc 1: the declaration was not
read, a declared IP names no RTL file, no top, or Yosys did not elaborate).
NOT_MEASURED exits 1 so no rc-reading consumer credits it: flow_compliance_check
reads rc 2 as a non-verdict it may promote to
VACUOUS_PASS.

chip-AGNOSTIC: parameter names and values come only from the manifests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling
import instrument_calibration as _calibration  # noqa: E402

PROGRAM = "catalog_synth_safe_params_check"
DECLARATION_REL = "plugin_output/declaration.json"
REPORT_REL = "reports/phase2/gates/catalog_synth_safe_params.json"
#: Where ``ip_catalog_query.load_project_facts`` reads the design's declaration.
DECLARATION_DOCS = (("phase1/generated_docs", "L*.json"), ("input/docs", "L*.md"))
YOSYS_JSON_REL = "reports/phase2/gates/catalog_synth_safe_params.yosys.json"
_PULLED = ("PASS", "PARTIAL")
#: FAIL code: the input declares the IP as reuse; the elaborated top never reaches it.
DECLARED_NOT_INSTANTIATED = "CATALOG_REUSE_DECLARED_NOT_INSTANTIATED"
#: FAIL code: a reached module of the IP elaborates a non-synth-safe value.
UNSAFE_PARAM = "CATALOG_SYNTH_SAFE_VALUE_NOT_PINNED"


def _safe_params(manifest: dict) -> dict[str, Any]:
    params = {}
    for entry in manifest.get("synth_safe_params") or []:
        if isinstance(entry, dict) and isinstance(entry.get("param"), str) \
                and "synth_safe_value" in entry:
            params[entry["param"]] = entry["synth_safe_value"]
    return params


def read_declaration(project: Path) -> tuple[list[str] | None, dict[str, Any]]:
    """``(declared catalog IP names, record)``; the names are None when unread.

    Every document ``declared_catalog_reuse`` reads must be present and parse.
    ``load_project_facts`` skips a document it cannot parse, so an unparseable
    L-doc would otherwise read as a design that names no IP.
    """
    import ip_catalog_query
    import _path_layout as layout
    original = layout.rtl_input(project) == "original"
    docs = (layout.original_input_sources(project) if original else
            [path for rel, pattern in DECLARATION_DOCS
             for path in sorted((project / rel).glob(pattern))])
    record: dict[str, Any] = {
        "source": "ip_catalog_query.declared_catalog_reuse",
        "documents": [str(p.relative_to(project)) for p in docs]}
    unreadable = []
    for path in docs:
        try:
            text = path.read_text()
            if not original and path.suffix == ".json":
                json.loads(text)
        except (OSError, ValueError):
            unreadable.append(str(path.relative_to(project)))
    if not docs:
        record["refused"] = ("declaration missing: no phase1/generated_docs/L*.json "
                             "or input/docs/L*.md")
        return None, record
    if unreadable:
        record["refused"] = f"declaration unreadable: {', '.join(unreadable)}"
        return None, record
    if not ip_catalog_query.load_manifests():
        record["refused"] = "the IP catalog has no loadable manifest"
        return None, record
    declared = ip_catalog_query.declared_catalog_reuse(project)
    record["declared_catalog_reuse"] = declared
    return declared, record


def judged_ips(project: Path, declared: list[str]) -> list[dict[str, Any]]:
    """The declared catalog IPs, plus any IP the pull record says was copied.

    A module belongs to an IP when its source file is one of the manifest's
    ``rtl_files`` or one ``ip_catalog_pull`` copied for it.
    """
    import ip_catalog_query
    manifests = {m.get("ip_name"): m for m in ip_catalog_query.load_manifests()}
    ips = {ip["ip_name"]: dict(ip, declared=False) for ip in pulled_ips(project)}
    for name in declared:
        manifest = manifests.get(name) or {}
        files = {Path(f).name for f in manifest.get("rtl_files") or []
                 if isinstance(f, str)}
        files |= set((ips.get(name) or {}).get("files") or [])
        ips[name] = {"ip_name": name, "files": sorted(files),
                     "params": _safe_params(manifest),
                     "manifest": manifest.get("_manifest_path"), "declared": True}
    return list(ips.values())


def pulled_ips(project: Path) -> list[dict[str, Any]]:
    """IPs ``ip_catalog_pull`` copied, with their manifests' synth-safe values."""
    import ip_catalog_query
    path = project / DECLARATION_REL
    try:
        declaration = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        declaration = {}
    used = declaration.get("ip_catalog_used") if isinstance(declaration, dict) else None
    manifests = {m.get("ip_name"): m for m in ip_catalog_query.load_manifests()}
    out = []
    for row in used if isinstance(used, list) else []:
        if not isinstance(row, dict) or row.get("status") not in _PULLED:
            continue
        manifest = manifests.get(row.get("ip_name")) or {}
        params = _safe_params(manifest)
        files = sorted({Path(str(f.get("dest"))).name
                        for f in row.get("files_copied") or []
                        if isinstance(f, dict) and f.get("dest")})
        out.append({"ip_name": row.get("ip_name"), "files": files, "params": params,
                    "manifest": manifest.get("_manifest_path")})
    return out


def top_synth_parameters(project: Path, top: str) -> tuple[list[str], str] | None:
    """``SYNTH_PARAMETERS`` for a top that IS a pulled catalog IP's module.

    LibreLane applies these with ``chparam -set <p> <v> <top>``, which reaches
    the top alone; an IP instantiated below the top is pinned by its glue and
    judged by ``run``. Returns ``(["p=v", ...], provenance)`` or None.
    """
    rtl = project / "phase2/stage1/rtl"
    for ip in pulled_ips(project):
        if not ip["params"]:
            continue
        for name in ip["files"]:
            path = rtl / name
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
            if re.search(r"\bmodule\s+" + re.escape(top) + r"\b", text):
                pins = [f"{k}={v}" for k, v in sorted(ip["params"].items())]
                return pins, (f"{ip['manifest'] or ip['ip_name']}.synth_safe_params "
                              f"(top {top} is defined in pulled {name})")
    return None


def _value(raw: Any) -> Any:
    """A Yosys JSON parameter value: bit string -> int, else the string."""
    if isinstance(raw, int):
        return raw
    text = str(raw)
    if re.fullmatch(r"[01]+", text):
        return int(text, 2)
    if re.fullmatch(r"[01xz]+", text):
        return None  # an x/z bit is not a value anybody pinned
    return text[:-1] if text.endswith(" ") else text


def judge(netlist: dict, ips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (elaborated module of a pulled IP, synth-safe parameter).

    ``netlist`` is Yosys's ``write_json`` after ``hierarchy -check -top``.
    """
    _calibration.assert_calibrated("catalog_synth_safe_params_check::judge")
    rows = []
    for name, module in sorted((netlist.get("modules") or {}).items()):
        attrs = module.get("attributes") or {}
        src = str(attrs.get("src", "")).split("|")[0].rsplit(":", 1)[0]
        values = module.get("parameter_default_values") or {}
        for ip in ips:
            if Path(src).name not in ip["files"]:
                continue
            for param, safe in ip["params"].items():
                if param not in values:
                    continue
                got = _value(values[param])
                rows.append({"ip_name": ip["ip_name"], "module": name,
                             "hdlname": attrs.get("hdlname", name), "param": param,
                             "value": got, "synth_safe_value": safe,
                             "safe": got == safe})
    return rows


def reached_ips(netlist: dict, ips: list[dict[str, Any]]) -> list[str]:
    """Names of the IPs with at least one module in the elaborated netlist.

    ``netlist`` is Yosys's ``write_json`` after ``hierarchy -check -top``,
    which drops every module the top does not reach. A module belongs to an
    IP by its ``src`` file, as in ``judge``; reaching needs no parameter.
    """
    _calibration.assert_calibrated("catalog_synth_safe_params_check::reached_ips")
    srcs = {Path(str((module.get("attributes") or {}).get("src", ""))
                 .split("|")[0].rsplit(":", 1)[0]).name
            for module in (netlist.get("modules") or {}).values()}
    return sorted(ip["ip_name"] for ip in ips if srcs & set(ip["files"]))


def _yosys(project: Path, image: str | None, script: str, out_dir: Path):
    """Host yosys, else the EDA image with only ``out_dir`` writable.

    ``image`` is the declared one (``--image`` / ``VIBEIC_EDA_IMAGE``); when
    nothing is declared the pinned image is resolved here, at use, never
    stored.
    """
    import shutil
    import subprocess
    if shutil.which("yosys"):
        command = ["yosys", "-q", "-p", script]
    elif shutil.which("docker"):
        import p0_tool_frontend_check as frontend
        image = image or frontend.default_image()
        root, out = str(project.resolve()), str(out_dir.resolve())
        command = ["docker", "run", *_dmem.docker_memory_flags(), "--rm",
                   "--network", "none", "-u",
                   f"{os.getuid()}:{os.getgid()}", "-v", f"{root}:{root}:ro",
                   "-v", f"{out}:{out}", "--entrypoint", "yosys", image,
                   "-q", "-p", script]
    else:
        raise FileNotFoundError("yosys and docker unavailable")
    return subprocess.run(command, cwd=project, capture_output=True, text=True,
                          check=False)


def run(project: Path, image: str | None) -> tuple[int, dict[str, Any]]:
    import p0_tool_frontend_check as frontend
    from _specrtl_common import rtl_source_files
    report: dict[str, Any] = {"program": PROGRAM, "project": str(project)}
    declared, report["declaration"] = read_declaration(project)
    if declared is None:
        report.update(verdict="NOT_MEASURED", reason=report["declaration"]["refused"])
        return 1, report
    judged = judged_ips(project, declared)
    ips = [ip for ip in judged if ip["params"]]
    # F28b: EVERY declared reuse is held to reachability, synth-safe values or
    # not; only the parameter judgement is limited to IPs that declare some.
    owed = [ip for ip in judged if ip.get("declared")]
    report["ips"] = ips
    report["declared_ips"] = owed
    if not ips and not owed:
        names = sorted(ip["ip_name"] for ip in judged)
        report.update(
            verdict="NOT_APPLICABLE", reason_class="DESIGN_DECLARED_NA",
            skip_kind="declaration-not-present",
            reason=(f"pulled catalog IP {names} is undeclared and declares no "
                    "synth_safe_params" if names else
                    "the design declares no catalog IP reuse and none was pulled"),
            applicability_evidence={
                "kind": "design-declared-zero-population",
                "population_paths": report["declaration"]["documents"],
                "declared_population": 0,
                "examined_files": report["declaration"]["documents"],
                "assertions": []})
        return 0, report
    unmapped = sorted(ip["ip_name"] for ip in owed if not ip["files"])
    if unmapped:
        report.update(verdict="NOT_MEASURED", reason=(
            f"declared catalog IP {unmapped} names no RTL file, so whether the "
            "top reaches it cannot be read"))
        return 1, report
    import _path_layout as layout
    if layout.rtl_input(project) == "original":
        from design_one_shot_runner import _v661_resolve_dut_module
        top = _v661_resolve_dut_module(project, "", None)
    else:
        top = frontend._top(project)
    files = [str(p.resolve()) for p in rtl_source_files(project)]
    if not top or not files:
        report.update(verdict="NOT_MEASURED",
                      reason="no L9 top_module or no RTL to elaborate")
        return 1, report
    out = project / YOSYS_JSON_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    script = ("read_verilog -sv " + " ".join(files) + f"; hierarchy -check -top {top}"
              f"; proc; write_json {out.resolve()}")
    try:
        result = _yosys(project, image, script, out.parent)
    except FileNotFoundError as exc:
        report.update(verdict="NOT_MEASURED", reason=str(exc))
        return 1, report
    report["yosys"] = {"exit_code": result.returncode,
                       "log_tail": (result.stdout + result.stderr)[-2000:]}
    try:
        netlist = json.loads(out.read_text())
    except (OSError, ValueError):
        netlist = None
    if result.returncode or not isinstance(netlist, dict):
        last = [line for line in (result.stdout + result.stderr).splitlines()
                if line.strip()][-1:] or ["no output"]
        report.update(verdict="NOT_MEASURED",
                      reason=f"Yosys did not elaborate the RTL: {last[0][-300:]}")
        return 1, report
    rows = judge(netlist, ips)
    report["instances"] = rows
    reached = reached_ips(netlist, judged)
    report["reached_ips"] = reached
    unreached = sorted(ip["ip_name"] for ip in owed if ip["ip_name"] not in reached)
    unsafe = [r for r in rows if not r["safe"]]
    codes, reasons = [], []
    if unreached:
        codes.append(DECLARED_NOT_INSTANTIATED)
        reasons.append(
            f"{DECLARED_NOT_INSTANTIATED}: the input declares catalog IP "
            f"{unreached} as reuse, but no module of it is reached from top {top}")
    if unsafe:
        codes.append(UNSAFE_PARAM)
        reasons.extend(
            f"{r['hdlname']} ({r['ip_name']}) elaborates {r['param']}={r['value']!r}, "
            f"synth-safe value is {r['synth_safe_value']!r}" for r in unsafe)
    if codes:
        report.update(verdict="FAIL", failure_codes=codes, reason="; ".join(reasons))
        return 1, report
    report.update(verdict="PASS", reason=(
        f"{len(rows)} elaborated IP module(s) carry their synth-safe values"
        if rows else (f"reached IP(s) {reached}: no reached module carries a "
                      "synth-safe parameter" if reached else
                      "no pulled, undeclared IP is reached from the top")))
    return 0, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--image", default=None)
    parser.add_argument("--rtl-input", choices=("structured", "original"), default="structured")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    import _path_layout as layout
    layout.select_rtl_input(project, args.rtl_input, "1", "2")
    image = args.image or os.environ.get("VIBEIC_EDA_IMAGE") or None
    rc, report = run(project, image)
    write_json(args.json or project / REPORT_REL, report)
    print(f"[{report['verdict']}] {PROGRAM}: {report['reason']}",
          file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

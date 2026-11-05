"""Publish native OpenROAD ERC using the final DEF and resolved PDK views."""
from pathlib import Path
import json
import re
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import phase3_one_shot_runner as R  # noqa: E402


def emit(project: Path, top: str, pdk: R.PdkConfig,
                     container: str, erc_rpt: Path, notes: list[str], *,
                     def_file: Path | None = None, image=None,
                     pdk_root: Path | None = None) -> bool:
    """ERC (Electrical Rule Check) — Step 31 sub-item, open-source path.

    sky130 ships only a Calibre PERC deck; the open-source path uses
    OpenROAD report_erc_metrics (floating-net / unconnected-pin electrical
    checks) on the routed DEF. Writes reports/phase3/erc.{rpt,json}.
    chip-AGNOSTIC. Best-effort."""
    if def_file is None:
        try:
            import librelane_postroute
            _, state = librelane_postroute.stapostpnr_state(project)
            def_file = Path(state['def'])
        except (OSError, ValueError, KeyError):
            def_file = R._pl.pnr_dir(project) / 'filled.def'
    def_file = Path(def_file)
    if not def_file.is_file():
        return False
    def_c = R._to_container_path(str(def_file), container)
    tech_lef_c = R._to_container_path(str(pdk.tech_lef), container)
    cell_lef_c = R._to_container_path(str(pdk.cell_lef), container)
    liberty_c = R._to_container_path(pdk.liberty, container)
    macro_lefs_tcl = "\n".join(
        f"read_lef {R._to_container_path(str(f), container)}"
        for f in pdk.macro_lefs)
    out_dir = erc_rpt.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir_c = R._to_container_path(str(out_dir), container)
    tcl_path = out_dir / f"erc_{top}.tcl"
    tcl_path.write_text(f"""
read_lef {tech_lef_c}
read_lef {cell_lef_c}
{macro_lefs_tcl}
{R._read_liberty_tcl(liberty_c)}
read_def {def_c}
puts "=== ERC: floating nets ==="
# v0.3.16 — ORGANIC #514: -verbose lists the floating net/pin NAMES so the
# by-owner classifier (erc_float_owner_classify.py) can tell benign
# design-for-ECO spare-cell I/O from a real functional float.
if {{[catch {{report_floating_nets -verbose}} _fn]}} {{ puts "ERC_FN_NONFATAL: $_fn" }}
puts "=== ERC metrics ==="
if {{[catch {{report_erc_metrics}} _erc]}} {{ puts "ERC_METRICS_NONFATAL: $_erc" }}
puts "ERC_NATIVE_DONE"
exit
""")
    tcl_c = R._to_container_path(str(tcl_path), container)
    cmd = (
        f"export PATH={R.TOOLS_IN_CONTAINER}/openroad/bin:"
        f"{R.TOOLS_IN_CONTAINER}/bin:$PATH && "
        f"openroad -no_init -exit {tcl_c} 2>&1 | tee {out_dir_c}/erc.log"
    )
    if image is None:
        rc, out, err = R._docker_exec(container, cmd, marker=tcl_c, outputs=[out_dir / "erc.log"])
    else:
        import librelane_contract as ll
        network, command = ll.native_tool_command(image, ['openroad', '-no_init', '-exit', str(tcl_path)])
        mounts = ['-v', f'{project.resolve()}:{project.resolve()}']
        if pdk_root:
            mounts += ['-v', f'{pdk_root.resolve()}:{pdk_root.resolve()}:ro']
        result = ll.run_container(['docker', 'run', '--rm', '--network', network,
            '--cpus', '4', '--memory', '16g', *mounts, image, '--skip', *command],
            supervised=True, log=out_dir / 'erc.log')
        rc, out, err = result.returncode, result.stdout, result.stderr
    log = (out or "") + "\n" + (err or "")
    if image is not None:
        (out_dir / 'erc.log').write_text(log)
    if rc or "ERC_NATIVE_DONE" not in log or "NONFATAL:" in log or "[ERROR" in log:
        notes.append(f"ERC NOT_MEASURED: native tool did not complete (rc={rc})")
        return False
    # v0.3.16 #514: also capture the -verbose floating net/pin NAME lines
    # (e.g. " spare_aoi_0/A1") so erc.rpt carries them for the by-owner
    # classifier, not just the summary counts.
    _name_re = re.compile(r'^\s+[A-Za-z0-9_\\\[\]/.$:]+\s*$')
    erc_lines = [ln for ln in log.splitlines()
                 if re.search(r"floating|erc|unconnect|ERC-", ln, re.I)
                 or _name_re.match(ln)]
    floating_m = re.search(r"(\d+)\s+floating net", log, re.I)
    floating = int(floating_m.group(1)) if floating_m else 0
    # Floating PINS (RSZ-0095: instance inputs with no net) are their own
    # count. The headline used to carry only the net count, so the spm tail
    # run shipped `ERC floating nets: 0 / ERC clean: YES` over a transcript
    # listing `spare_dff_0/CLK` as a floating pin (U6).
    fpins_m = re.search(r"(\d+)\s+floating pin", log, re.I)
    floating_pins = int(fpins_m.group(1)) if fpins_m else 0
    # v0.3.16 #514: classify the verbose floats by owner so the runner can
    # tell benign design-for-ECO spare-cell I/O from a real functional
    # float. Best-effort (the classifier lives in its own program).
    erc_classification = None
    try:
        import erc_float_owner_classify as _efc
        _floats = _efc.parse_floats(log)
        erc_classification = _efc.classify(
            _floats, input_pins=_efc.parse_floating_input_pins(log))
    except Exception:
        erc_classification = None
    _erc_clean = floating == 0 and floating_pins == 0
    body = (
        "# Electrical Rule Check (ERC) — OpenROAD open-source path\n"
        "# (ORGANIC-20260531 Step 31 sub-item). Tool: openroad.\n"
        "# sky130 ships only a Calibre PERC deck; this is the open-source\n"
        "# electrical-rule screen (floating nets + ERC metrics) on the\n"
        "# routed DEF. Full PERC (latch-up / ESD topology) needs Calibre.\n"
        "#\n"
        f"ERC floating nets: {floating}\n"
        f"ERC floating pins: {floating_pins}\n"
        f"ERC clean: {'YES' if _erc_clean else 'NO (review floating nets/pins)'}\n"
        "\n# === report_floating_nets / report_erc_metrics stdout ===\n"
        + ("\n".join(erc_lines) or "(no ERC lines captured)") + "\n"
        "\n# === full ERC log (last 2 KB) ===\n" + log[-2000:] + "\n"
        "# end of erc.rpt\n")
    erc_rpt.write_text(body)
    # v0.3.16 #514: a float set that is 100% benign-by-construction
    # (design-for-ECO spare-cell I/O) is waiver-eligible, not a raw REVIEW.
    _benign = bool(erc_classification
                   and erc_classification.get("classification") == "benign-ERC")
    _erc_verdict = ("PASS" if _erc_clean
                    else "BENIGN-ERC" if _benign else "REVIEW")
    (erc_rpt.parent / "erc.json").write_text(json.dumps({
        "tool": "openroad",
        "mode": "erc_floating_nets_and_metrics",
        "floating_nets": floating,
        "floating_pins": floating_pins,
        "clean": _erc_clean,
        "source": str(erc_rpt.relative_to(project)),
        "def": str(def_file),
        "verdict": _erc_verdict,
        # v0.3.16 #514 — by-owner classification of the floats.
        "float_classification": erc_classification,
        "note": ("open-source ERC screen; full Calibre PERC "
                 "(latch-up/ESD) deferred"),
    }, indent=2) + "\n")
    return True

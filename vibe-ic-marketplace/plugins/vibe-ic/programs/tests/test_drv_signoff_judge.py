"""DRV standard: a measured bad value must fail, and a clean value must pass."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))






def _file(root: Path, name: str, body: str) -> dict:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return {"path": str(path), "sha256": hashlib.sha256(body.encode()).hexdigest()}


def _capture_rcx_fixture(plan, root):
    """Capture fixtures include the RCX producer's existing input/output record."""
    scene = plan["scenes"][0]
    scene["spef"] = _file(root, "rcx/nom/top.nom.spef",
                          Path(scene["spef"]["path"]).read_text())
    layout = plan["identity"]["artifacts"]["def"]
    _file(root, "rcx/COMMANDS", "openroad -exit native-rcx.tcl\n")
    _file(root, "rcx/vibeic_receipt.json", json.dumps({
        "input": {"step": "OpenROAD.RCX",
                  "image": plan["identity"]["tool_image"],
                  "state_files": {layout["path"]: layout["sha256"]}},
        "sha256": {"nom/top.nom.spef": scene["spef"]["sha256"]}}))


def _report(*, fanout=1, fanout_limit=4, cap=.1, cap_limit=.2,
            slew=.1, slew_limit=3, violators=False) -> str:
    parts = []
    for title, limit_label, measured_label, value, limit, direction in (
        ("max slew", "max slew", "slew", slew, slew_limit, "^"),
        ("max fanout", "max fanout", "fanout", fanout, fanout_limit, ""),
        ("max capacitance", "max capacitance", "capacitance", cap, cap_limit, "^"),
    ):
        parts.append(title + "\n")
        if not violators or value > limit:
            slack = limit - value
            parts.extend((f"Pin u/Y {direction}\n", f"{limit_label} {limit:.6f}\n",
                          f"{measured_label} {value:.6f}\n",
                          f"Slack {slack:.6f} " +
                          ("(VIOLATED)" if slack < 0 else "(MET)") + "\n"))
        parts.append("\n")
    return "".join(parts)










def _owner_waiver(bundle: dict, root: Path, row: dict) -> dict:
    netlist = bundle["identity"]["sta_netlist"]
    sdc = bundle["current"]["sources"]["signoff_sdc"]["sha256"]
    return {"netlist_sha256": netlist, "tree_sha": "tree-a", "run_id": "run-1",
            "driver_pin": "u/Y", "driver_cell": "logic",
            "measured": row["measured"], "limit": row["effective_limit"],
            "scene_or_mode": (row["mode"] if row["kind"] == "max_fanout"
                              else row["scene"]), "sdc_sha256": sdc,
            "issuer": "reyerchu", "origin": "owner",
            "owner_quote": "Approve this one measured net",
            "owner_timestamp": "2026-09-28T10:00:00+08:00", "approved_value": row["measured"],
            "timing": [{"scene": "typ_nom", "netlist_sha256": netlist,
                        "sdc_sha256": sdc, "period_ns": 24,
                        "io_delay_ns": 4.8, "setup_slack_ns": 1,
                        "hold_slack_ns": .1,
                        "report": _file(root, "timing.rpt",
                                        "worst slack max 1\nworst slack min 0.1\n")}],
            "signal_em": {"scene": "typ_nom", "worst_scene": True,
                          "netlist_sha256": netlist,
                          "report": _file(root, "em.rpt", json.dumps({
                              "currents": {"average": .1, "rms": .2, "peak": .3},
                              "limits": {"average": 1, "rms": 1, "peak": 1}})),
                          "drm_source": _file(root, "drm.txt", "current limits\n"),
                          "currents": {"average": .1, "rms": .2, "peak": .3},
            "limits": {"average": 1, "rms": 1, "peak": 1}}}


















































































































def _neutral_registered_owner_key(root):
    """Public fixture only; no owner key or private key is read or created."""
    import base64
    import struct
    public = b'ssh-ed25519'
    blob = struct.pack('>I', len(public)) + public + struct.pack('>I', 32) + bytes(range(32))
    path = root / 'neutral_allowed_signers'
    path.write_text('owner ssh-ed25519 ' + base64.b64encode(blob).decode() + '\n')
    return path




















































































# --- DRVWIRE review wave 56: capture plan stage rows, step-32 layout binding
# and port-to-PAD SPEF connectivity (R-0928-DRV-IC).

def _port_pad_pins() -> dict:
    return {"p": {"kind": "port", "cell": None, "cell_pin": None,
                  "cell_class": "port", "net": "p"},
            "u/PAD": {"kind": "pin", "cell": "pad", "cell_pin": "PAD",
                      "cell_class": "IO", "net": "p"}}


def _port_pad_scene(tmp_path: Path, spef_body: str, def_nets: str):
    folder = tmp_path / "scene"
    _file(folder, "annotation.rpt", "Found 1 unannotated drivers.\n p\n"
          "Found 0 partially unannotated drivers.\n")
    lef = _file(tmp_path, "pad.lef", "MACRO pad\n PIN PAD\n USE SIGNAL ;\n"
                " END PAD\nEND pad\n")
    lib = _file(tmp_path, "pad.lib", '''library (lib) {
 time_unit : "1ns"; capacitive_load_unit (1, pf);
 cell (pad) { pad_cell : true;
  pin (PAD) { direction : input; timing () { related_pin : "PAD"; } }
 }
}''')
    routed = _file(tmp_path, "route.def", "NETS 1 ;\n" + def_nets + "END NETS\n")
    spef = _file(tmp_path, "route.spef", spef_body)
    return (folder, _port_pad_pins(), [lib], [lef], Path(routed["path"]),
            Path(spef["path"]))


_ROUTED_P = " - p ( PIN p ) ( u PAD ) + ROUTED Metal2 ( 0 0 ) ( 10 0 ) ;\n"






















# ── R-0928-DRV-IC / root audit U1: the port-to-PAD net is off-chip ──────────
# MEASURED on the routed spm DIE (lane drvrcpt, 9 scenes): 35 bond-pad input
# ports read 2.9-3.1 pF (the pad's own PAD-pin capacitance) against the
# std-cell 0.2 pF margin, and the judge booked 315 T3_MARGIN cap rows plus
# 306 T3 / 9 T2 port slew rows. The pad pin's own row (IO Liberty T1) carries
# the same slew and stays a finding.

def _port_row(bundle, *, port_to_pad):
    bundle["pins"]["u/Y"] = {"net_class": "IO", "cell_class": "port",
                             "cell": None, "cell_pin": None, "liberty": None,
                             "driver_pin": "u/Y", "driver_cell": None,
                             "port_to_pad": port_to_pad,
                             "loads": {"logical": 1, "antenna_diode": 0,
                                       "cts_buffer": 0}}


































def _fresh_cid_launch_attempt(capture, script, journal):
    try:
        output = capture._run_fresh(script, {script.parent}, image='source-control:image')
        observed = {'outcome': 'RETURNED', 'output': output}
    except RuntimeError as exc:
        observed = {'outcome': 'REFUSED', 'reason': str(exc)}
    call = json.loads(journal.read_text().splitlines()[-1])
    argv = call['argv']
    observed.update(cidfile=argv[argv.index('--cidfile') + 1],
                    name=argv[argv.index('--name') + 1], docker_boundary=call,
                    raw=script.with_suffix('.tool.log').read_text())
    return observed











# Keep the real installed-image reader available after this module's synthetic
# image fixture; this LOCAL control uses the actual outer launch attestation.

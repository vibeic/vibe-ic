#!/usr/bin/env python3
"""Native well/tap electrical connectivity checks using the IHP LVS extractor.

The installed foundry deck is never changed. A source-hashed local derivative
uses KLayout's directional soft connections for well/tap paths and checks the
actual extracted MOS bulk nets for a physical metal connection. This is well
connectivity ERC; voltage stress/SOA remains a separate simulation analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import uuid
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_INCLUDE = re.compile(r"^\s*#\s*%include\s+(\S+)\s*$", re.M)

# A version mismatch here is an unsupported source shape, never a clean ERC.
_SOFT = {
    "connect(pwell, ptap)": "soft_connect(ptap, pwell)",
    "connect(nwell_drw, ntap)": "soft_connect(ntap, nwell_drw)",
    "connect(ntap, cont_drw)": "soft_connect(cont_drw, ntap)",
    "connect(ptap, cont_drw)": "soft_connect(cont_drw, ptap)",
    "connect(ntap1_tie, cont_drw)": "soft_connect(cont_drw, ntap1_tie)",
    "connect(ptap1_tie, cont_drw)": "soft_connect(cont_drw, ptap1_tie)",
    "connect(ntap1_tie, ntap1_well)": "soft_connect(ntap1_tie, ntap1_well)",
    "connect(ptap1_tie, ptap1_sub)": "soft_connect(ptap1_tie, ptap1_sub)",
}
_METALS = ("metal1_con", "metal2_con", "metal3_con", "metal4_con",
           "metal5_con", "topmetal1_con", "topmetal2_con")

_CAPTURE = r'''
# Native ERC capture before any simplification/purging of extracted terminals.
require 'json'
erc_netlist = netlist
erc_logs = l2n_data.each_log_entry.map { |e| {'text' => e.to_s} }
erc_error = nil
begin
  l2n_data.check_extraction_errors
rescue => e
  erc_error = e.message
end
erc_metal_indexes = l2n_data.layer_indexes.select { |i| l2n_data.layer_name(i).start_with?('ERC_METAL_') }
erc_soft_indexes = l2n_data.layer_indexes.to_h { |i| [l2n_data.layer_name(i), i] }
erc_soft_edges = __ERC_SOFT_EDGES__
erc_bodies = []
erc_devices = 0
erc_netlist.each_circuit do |c|
  # Native soft-net joining deliberately omits floating nets. A labelled metal
  # tie can therefore remain separate before top-level pins are made. Read its
  # physical path through exactly the source-declared soft materials instead;
  # never join nets or add pins to make the check pass.
  nets = c.each_net.to_a
  regions = {}
  nets.each do |n|
    regions[n.cluster_id] = {}
    (erc_metal_indexes + erc_soft_edges.flatten.map { |name| erc_soft_indexes.fetch(name) }).uniq.each do |i|
      r = l2n_data.polygons_of_net(n, i)
      regions[n.cluster_id][i] = r unless r.is_empty?
    end
  end
  c.each_device do |d|
    erc_devices += 1
    next unless d.device_class.is_a?(RBA::DeviceClassMOS4Transistor)
    bulk = d.net_for_terminal('B')
    metal_tied = bulk && erc_metal_indexes.any? { |i| !l2n_data.polygons_of_net(bulk, i).is_empty? }
    queue = bulk && !metal_tied ? [bulk.cluster_id] : []
    paths = bulk ? {bulk.cluster_id => []} : {}
    tie_path = metal_tied ? [] : nil
    until queue.empty?
      current = queue.shift
      if erc_metal_indexes.any? { |i| regions[current].has_key?(i) }
        metal_tied = true
        tie_path = paths[current]
        break
      end
      erc_soft_edges.each do |lower_name, upper_name|
        lower = regions[current][erc_soft_indexes.fetch(lower_name)]
        next unless lower
        nets.each do |other|
          target = other.cluster_id
          next if paths.has_key?(target)
          upper = regions[target][erc_soft_indexes.fetch(upper_name)]
          next unless upper && lower.bbox.touches?(upper.bbox)
          next if lower.interacting(upper).is_empty?
          paths[target] = paths[current] + [{'from_cluster' => current,
            'to_cluster' => target, 'lower_layer' => lower_name,
            'upper_layer' => upper_name, 'overlap_area_dbu2' => (lower & upper).area}]
          queue << target
        end
      end
    end
    erc_bodies << {'circuit'=>c.name, 'device'=>d.expanded_name,
      'device_class'=>d.device_class.name, 'bulk_net'=>bulk && bulk.expanded_name,
      'metal_tied'=>!!metal_tied, 'native_soft_tie_path'=>tie_path}
  end
end
File.write($erc_json, JSON.pretty_generate({'engine'=>'KLayout LayoutToNetlist',
  'scope'=>'MOS well/substrate metal ties and soft-connected well/tap routing',
  'extracted_devices'=>erc_devices, 'mos_bodies'=>erc_bodies,
  'native_logs'=>erc_logs, 'native_extraction_error'=>erc_error}))
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _flatten(files: dict[str, str], root: str, stack=()) -> str:
    if root in stack:
        raise ValueError(f"recursive foundry include: {root}")
    if root not in files:
        raise ValueError(f"missing foundry include: {root}")
    parent = Path(root).parent
    return _INCLUDE.sub(lambda m: _flatten(files, str(parent / m[1]), (*stack, root)),
                        files[root])


def _derive(text: str) -> str:
    for source, replacement in _SOFT.items():
        if text.count(source) != 1:
            raise ValueError(f"unsupported foundry connectivity: {source}")
        text = text.replace(source, replacement)
    setup = "logger.info('Starting SG13G2 LVS connectivity setup')"
    capture = "# RF MOS model mapping"
    if text.count(setup) != 1 or text.count(capture) != 1:
        raise ValueError("unsupported foundry LVS execution layout")
    pairs = [re.fullmatch(r"soft_connect\((\w+), (\w+)\)", value).groups()
             for value in _SOFT.values()]
    soft_layers = sorted({layer for pair in pairs for layer in pair})
    names = "\n".join([*(f"name({m}, 'ERC_METAL_{i}')" for i, m in enumerate(_METALS)),
                       *(f"name({layer}, 'ERC_SOFT_{layer}')" for layer in soft_layers)])
    text = text.replace(setup, "top_level(true)\nignore_extraction_errors(true)\n" + names + "\n" + setup)
    # _SOFT declares upper -> lower. The physical well-tie search follows the
    # same native geometry from the bulk upward; no additional edges are added.
    edges = [[f"ERC_SOFT_{lower}", f"ERC_SOFT_{upper}"] for upper, lower in pairs]
    native_capture = _CAPTURE.replace("__ERC_SOFT_EDGES__", json.dumps(edges))
    return text.replace(capture, native_capture + "\n" + capture)


def grade(record: dict, returncode: int) -> tuple[str, str]:
    if returncode in (125, 127) and not record:
        return "NOT_MEASURED", "native ERC tool or selected container is unavailable"
    if returncode:
        return "FAIL", f"native ERC extraction exited {returncode}"
    if record.get("native_extraction_error"):
        return "FAIL", "native electrical connectivity extraction reported errors"
    bodies = record.get("mos_bodies")
    if not isinstance(bodies, list) or not bodies:
        return "NOT_MEASURED", "no MOS bulk terminals were extracted for ERC"
    if any(not isinstance(b, dict) or b.get("metal_tied") is not True for b in bodies):
        return "FAIL", "extracted MOS well/substrate lacks a physical metal tie"
    return "PASS", "native MOS well/tap electrical connectivity is clean"


def select_deck(project: Path, resolved: dict, pdk: str) -> str:
    """Select a declared KLayout extraction deck, never a Netgen setup file."""
    candidates = [resolved.get("erc_deck"), resolved.get("lvs_deck"),
                  *(resolved.get("lvs_deck_candidates") or [])]
    for path in candidates:
        if path and Path(path).suffix.lower() == ".lvs":
            return str(path)
    if str(pdk).lower() in ("ihp-sg13g2", "sg13g2"):
        staged = Path(project) / "input/pdk/klayout/tech/lvs/sg13g2.lvs"
        if staged.is_file():
            return str(staged)
        if resolved.get("klayout_dir"):
            return str(Path(resolved["klayout_dir"]) / "tech/lvs/sg13g2.lvs")
    return ""


def run(project: Path, block: str, *, container: str, lvs_deck: str,
        output_dir: Path | None = None) -> dict:
    import analog_a6_native_pv as pv
    project = Path(project).resolve()
    bdir = project / "phase3" / "analog" / block
    gds = bdir / f"{block}.gds"
    if not container or not gds.is_file() or not lvs_deck:
        return {"status": "NOT_MEASURED", "detail": "native container, block GDS and foundry LVS deck are required", "outputs": []}
    work = output_dir or project / "continuations" / "native-erc" / f"{block}-{uuid.uuid4().hex[:12]}"
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=False)
    native = work / "native.json"
    deck = work / "well_connectivity.lvs"
    transcript = work / "klayout.log"
    # Fetch exactly the transitive source closure from the actual native image.
    fetch = """import json,re\nfrom pathlib import Path\nfiles={}\ndef visit(p):\n p=p.resolve()\n if str(p) in files:return\n t=p.read_text();files[str(p)]=t\n for n in re.findall(r'^\\s*#\\s*%include\\s+(\\S+)\\s*$',t,re.M):visit(p.parent/n)\nroot=Path(__DECK__).resolve()\nvisit(root)\nprint('ERC_SOURCE='+json.dumps({'root':str(root),'files':files}))\n""".replace("__DECK__", repr(lvs_deck))
    rc, out, err = pv._docker_exec_raw(container, "python3 -c " + shlex.quote(fetch))
    if rc:
        transcript.write_text(out + err)
        return {"status": "NOT_MEASURED", "detail": "foundry native ERC source closure unavailable", "outputs": [str(transcript)]}
    try:
        payloads = [line.removeprefix("ERC_SOURCE=") for line in out.splitlines()
                    if line.startswith("ERC_SOURCE=")]
        if len(payloads) != 1:
            raise ValueError("native source closure did not return exactly one payload")
        closure = json.loads(payloads[0])
        files = closure["files"]
        flat = _flatten(files, closure["root"])
        derived = _derive(flat)
    except (ValueError, KeyError, TypeError) as exc:
        transcript.write_text(str(exc))
        return {"status": "NOT_MEASURED", "detail": str(exc), "outputs": [str(transcript)]}
    deck.write_text(derived)
    source_views = {"foundry:" + p: {"path": p, "sha256": hashlib.sha256(t.encode()).hexdigest()} for p, t in files.items()}
    sources = work / "foundry_sources.json"
    sources.write_text(json.dumps(files, indent=2) + "\n")
    before = {"gds": {"path": str(gds), "sha256": _sha(gds)},
              "erc_deck": {"path": str(deck), "sha256": _sha(deck)},
              "foundry_sources": {"path": str(sources), "sha256": _sha(sources)}}
    argv = ["klayout", "-b", "-r", str(deck), "-rd", f"input={gds}",
            "-rd", f"report={work / 'erc.lvsdb'}", "-rd", f"log={work / 'foundry.log'}",
            "-rd", f"target_netlist={work / 'extracted.cir'}", "-rd", f"erc_json={native}",
            "-rd", "net_only=true", "-rd", "no_simplify=true", "-rd", "disable_tap_extraction=true"]
    command = shlex.join(argv)
    (work / "command.json").write_text(json.dumps({"container": container, "argv": argv}, indent=2) + "\n")
    rc, out, err = pv._docker_exec(container, command, marker=f"analog-erc-{block}-{work.name}", log_path=transcript)
    transcript.write_text(out + err)
    try:
        record = json.loads(native.read_text())
        if not isinstance(record, dict): record = {}
    except (OSError, ValueError):
        record = {}
    status, detail = grade(record, rc)
    if _sha(gds) != before["gds"]["sha256"] or _sha(deck) != before["erc_deck"]["sha256"]:
        if status != "FAIL": status, detail = "NOT_MEASURED", "ERC layout/deck changed during native extraction"
    record.update(status=status, detail=detail, returncode=rc, native_inputs=before,
                  foundry_sources=source_views,
                  outputs=[str(p) for p in (native, deck, sources, transcript, work / "command.json", work / "erc.lvsdb", work / "extracted.cir") if p.is_file()])
    result = work / "result.json"
    result.write_text(json.dumps(record, indent=2) + "\n")
    record["outputs"].append(str(result))
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--lvs-deck", required=True)
    ap.add_argument("--output-dir", type=Path)
    args = ap.parse_args()
    result = run(args.project, args.block, container=args.container, lvs_deck=args.lvs_deck, output_dir=args.output_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

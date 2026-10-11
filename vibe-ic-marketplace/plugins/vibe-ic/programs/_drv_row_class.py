"""Class a sign-off DRV violator row the way the DRV standard judges it.

OpenSTA holds one design-wide `set_max_capacitance` / `set_max_transition`
margin for every driver, top-level ports and IO-cell pins included: its checker
reads the top-cell, port and Liberty limits only (a pin-scoped limit is never
read) and a port can only be tightened below the design limit. On a pad-ring
(DIE) top that puts the std-cell margin on nets no std cell drives:

* a bond-pad PORT whose net reaches only IO-cell pins (the port-to-PAD net).
  Its "load" is the pad's own PAD-pin capacitance (2.9-3.1 pF on gf180) and its
  "slew" is the off-chip drive. R-0928-DRV-IC: such a net is judged by the IO
  Liberty T1 on the IO-cell pin (that row stays in the table under its own name)
  and by the declared or PDK set_load -- never by the std-cell margin;
* an IO-cell pin whose tool limit is the std-cell margin while its measured
  value is within the IO Liberty limit (DRV standard section 4: listed apart,
  not a gate, pending the owner). Above the IO Liberty limit it stays T1.

Every other row counts, including every IO-cell row at its Liberty limit (the
IO library's default_max_fanout 1 is fix-only). A row is taken out of the count
only on complete, source-bound OpenSTA connectivity and linked IO Liberty;
anything unprovable counts, and an unreadable input raises `Unavailable`.

chip-AGNOSTIC: an IO cell is a cell the run's own PAD_LIBS Liberty marks
`pad_cell : true` -- the DRV judge's definition, read by its own reader.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ONE implementation of each class rule: the DRV judge's (this module only
# gathers the inputs -- the run's netlist, its IO Liberty, its cap margin).
from drv_signoff_judge import (IO_STD_CELL_MARGIN_DISCLOSURE as IO_MARGIN,  # noqa: E402
                               OFFCHIP_PORT_TO_PAD_NET as OFFCHIP_PORT,
                               _liberty_limits, _sdc_values, _sha, io_margin_disclosure)

COUNTED = "DRV"


class Unavailable(RuntimeError):
    """The netlist or an IO Liberty the classes need could not be read."""


def _name(token: str) -> str:
    token = token.strip()
    return token[1:].strip() if token.startswith("\\") else token


def netlist_nets(text: str) -> Dict[str, List[Tuple[str, str, str]]]:
    """{net: [(instance, master, pin)]} from a flat or hierarchical-name
    structural Verilog netlist (named port connections only).

    Used only to identify instance masters for IO Liberty margin disclosure.
    This partial reader NEVER proves connectivity or a port exclusion.
    """
    nets: Dict[str, List[Tuple[str, str, str]]] = {}
    body = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    body = re.sub(r"//[^\n]*", " ", body)
    for m in re.finditer(r"(?m)^\s*(\\?[A-Za-z_][\w$]*)\s+(\\\S+\s|[A-Za-z_][\w$\[\]]*)\s*"
                         r"\((.*?)\)\s*;", body, re.S):
        master, inst = m.group(1), _name(m.group(2))
        if master in ("module", "input", "output", "inout", "wire", "assign", "reg"):
            continue
        for c in re.finditer(r"\.(\w+)\s*\(\s*(\\\S+\s|[^()\s]+)\s*\)", m.group(3)):
            nets.setdefault(_name(c.group(2)), []).append((inst, master, c.group(1)))
    return nets


class Classifier:
    """Classes of (corner, kind, pin, limit, value) rows for one sign-off run."""

    def __init__(self, netlist: Path, pad_libs: Mapping[str, Sequence[Path]],
                 cap_margin: Optional[float] = None, *, project: Optional[Path] = None,
                 sdc: Optional[Path] = None):
        """`cap_margin`: the design-scope std-cell cap margin the run's
        sign-off SDC applied (None: the IO-margin class never applies)."""
        self._cap_margin = cap_margin
        try:
            self._nets = netlist_nets(Path(netlist).read_text(errors="replace"))
        except OSError as exc:
            raise Unavailable(f"netlist {netlist} unreadable: {exc}") from exc
        if not self._nets:
            raise Unavailable(f"netlist {netlist} names no instance connection")
        self._inst_master = {inst: master for conns in self._nets.values()
                             for inst, master, _ in conns}
        self._libs: Dict[str, List[dict]] = {}
        for corner, paths in pad_libs.items():
            parsed = []
            for path in paths:
                try:
                    parsed.append(_liberty_limits(Path(path).read_text(errors="replace")))
                except (OSError, ValueError) as exc:
                    raise Unavailable(f"IO Liberty {path} unreadable: {exc}") from exc
            self._libs[corner] = parsed
        self._ports: Dict[str, set] = {}
        self.connectivity_evidence = {"state": "UNAVAILABLE",
                                      "reason": "no current OpenSTA connectivity bundle; port and IO rows counted"}
        if project is not None and sdc is not None:
            self._connectivity(Path(project), Path(netlist), Path(sdc), pad_libs)

    def _connectivity(self, project: Path, netlist: Path, sdc: Path,
                      pad_libs: Mapping[str, Sequence[Path]]) -> None:
        """Reuse the existing capture's raw census, never its asserted classes.

        The current run, netlist, SDC, linked libraries and raw report hashes
        must agree. A stale, absent or malformed witness leaves port and IO
        rows counted; replacement Liberty bytes cannot reinterpret old rows.
        A DRV FAIL is still useful connectivity evidence; no verdict is upgraded.
        """
        from drv_signoff_census import _pins, _nets, port_connectivity
        from drv_signoff_annotation import _is_physical_pin, _lef_pin_models
        import drv_run_identity
        source = project / "reports/phase3/sta/drv_signoff_bundle.json"

        def checked(ref):
            if not isinstance(ref, dict) or not ref.get("path"):
                raise ValueError("connectivity evidence reference absent")
            path = Path(ref["path"])
            if not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256") or "")) or _sha(path) != ref["sha256"]:
                raise ValueError(f"connectivity evidence changed: {path}")
            return path

        try:
            bundle = json.loads(source.read_text())
            identity = bundle["identity"]
            run = drv_run_identity.load(project)
            if (not run.get("run_id") or not run.get("plugin_tree_sha256") or
                    identity.get("run_id") != run["run_id"] or
                    identity.get("tree_sha") != run["plugin_tree_sha256"] or
                    Path(identity["project"]).resolve() != project.resolve()):
                raise ValueError("connectivity capture differs from current run identity")
            nl_ref = identity["artifacts"]["sta_netlist"]
            if checked(nl_ref).resolve() != netlist.resolve() or nl_ref["sha256"] != _sha(netlist):
                raise ValueError("connectivity capture differs from current netlist")
            sdc_ref = bundle["current"]["sources"]["signoff_sdc"]
            if checked(sdc_ref).resolve() != sdc.resolve() or sdc_ref["sha256"] != _sha(sdc):
                raise ValueError("connectivity capture differs from current sign-off SDC")
            if (not identity.get("opensta_commit") or
                    not re.fullmatch(r"sha256:[0-9a-f]{64}", str(identity.get("tool_image_digest") or ""))):
                raise ValueError("OpenSTA tool identity absent")
            scenes = bundle["scenes"]
            if not isinstance(scenes, list) or not scenes:
                raise ValueError("OpenSTA connectivity scenes absent")
            ports = {}
            evidence = {}
            for corner, paths in pad_libs.items():
                required = {_sha(Path(p)) for p in paths}
                linked = set()
                proofs = []
                refs = []
                for scene in scenes:
                    name = scene["name"]
                    pvt, _, rc = name.rpartition("_")
                    if corner != "*" and corner not in (name, f"{rc}_{pvt}"):
                        continue
                    if scene.get("fresh_process") is not True:
                        raise ValueError("connectivity census lacks fresh-process receipt")
                    scene_libs = scene["linked_liberties"]
                    hashes = set()
                    pads = set()
                    limits = []
                    for item in scene_libs:
                        lib = checked(item)
                        hashes.add(item["sha256"])
                        parsed = _liberty_limits(lib.read_text())
                        limits.append(parsed)
                        pads.update(parsed["pad_cells"])
                    linked.update(hashes)
                    pin_ref, net_ref = scene["pin_census_report"], scene["net_census_report"]
                    pin_path, net_path = checked(pin_ref), checked(net_ref)
                    if pin_path.parent != net_path.parent:
                        raise ValueError("OpenSTA pin/net census comes from different scenes")
                    pins = _pins(pin_path)
                    lef_refs = scene.get("linked_lefs") or []
                    for item in lef_refs:
                        checked(item)
                    lef_models = _lef_pin_models(lef_refs) if lef_refs else {}
                    modeled_cells = {cell for lib in limits for cell in lib["cells"]}
                    for pin, item in pins.items():
                        if item["kind"] == "pin" and item.get("net"):
                            matches = [lib for lib in limits if item["cell_pin"] in
                                       lib["cells"].get(item["cell"], {})]
                            if len(matches) != 1:
                                if not matches and _is_physical_pin(item, lef_models, modeled_cells):
                                    continue
                                raise ValueError(f"OpenSTA pin {pin} lacks unique linked Liberty identity")
                    proofs.append(port_connectivity(pins, _nets(net_path), pads))
                    refs.append({"scene": name, "pins": pin_ref, "nets": net_ref,
                                 "unconnected_core_inputs": [p for p, item in pins.items()
                                     if item["kind"] == "pin" and item.get("direction") in ("input", "inout")
                                     and not item.get("net") and item.get("cell") not in pads]})
                if not proofs or not required.issubset(linked):
                    raise ValueError(f"no complete linked IO connectivity witness for {corner}")
                ports[corner] = {p for p in proofs[0] if all(proof.get(p) is True for proof in proofs)}
                evidence[corner] = refs
            self._ports = ports
            self.connectivity_evidence = {"state": "SOURCE_BOUND", "bundle": str(source),
                                          "sha256": _sha(source), "scenes": evidence}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.connectivity_evidence = {"state": "UNAVAILABLE", "bundle": str(source),
                                          "reason": f"{exc}; port and IO rows counted"}

    def _io(self, corner: str) -> List[dict]:
        if corner not in self._libs:
            raise Unavailable(f"no IO Liberty for corner {corner}")
        return self._libs[corner]

    def _pad(self, corner: str, master: Optional[str]) -> Optional[dict]:
        """The IO Liberty that declares `master` a pad cell (the judge's IO
        class: `pad_cell : true`), or None."""
        for lib in self._io(corner):
            if master in lib["pad_cells"]:
                return lib
        return None

    def io_limit(self, corner: str, master: str, pin: str, kind: str) -> Optional[float]:
        """The tightest IO Liberty limit over every linked library that
        declares `master` a pad cell (one per corner in a scene; all of them
        when a report spans corners)."""
        limits = []
        for lib in self._io(corner):
            if master not in lib["pad_cells"]:
                continue
            value = (lib["cells"].get(master, {}).get(pin) or {}).get(kind)
            value = value if value is not None else lib["defaults"].get(kind)
            if value is not None:
                limits.append(value)
        return min(limits) if limits else None

    def classify(self, corner: str, kind: str, pin: str,
                 limit: Optional[float], value: Optional[float]) -> str:
        if "/" not in pin:
            return OFFCHIP_PORT if pin in self._ports.get(corner, set()) else COUNTED
        # Both exemptions need the same current run/netlist/SDC/linked-library
        # binding. _ports is populated atomically only after that check passes.
        if corner not in self._ports:
            return COUNTED
        inst, _, lib_pin = pin.rpartition("/")
        master = self._inst_master.get(inst)
        if self._pad(corner, master) is None:
            return COUNTED
        return (IO_MARGIN if io_margin_disclosure(
            kind, "IO", None, limit, value,
            self.io_limit(corner, master, lib_pin, kind), self._cap_margin)
            else COUNTED)


def sdc_cap_margin(sdc_text: str) -> Optional[float]:
    """The one design-scope `set_max_capacitance <v> [current_design]` value
    the sign-off SDC applies, or None when absent or ambiguous."""
    values = {v for v in _sdc_values(sdc_text, "set_max_capacitance", include_ports=False)}
    return values.pop() if len(values) == 1 else None


def pad_libs_by_corner(pad_libs: object, corners: Iterable[str]) -> Dict[str, List[str]]:
    """LibreLane PAD_LIBS (a corner-glob map, or one list for every corner)."""
    out: Dict[str, List[str]] = {}
    for corner in corners:
        if isinstance(pad_libs, dict):
            hits = [p for glob, paths in pad_libs.items()
                    if fnmatch.fnmatch(corner, glob)
                    for p in ([paths] if isinstance(paths, str) else paths)]
        else:
            hits = [pad_libs] if isinstance(pad_libs, str) else list(pad_libs or [])
        if hits:
            out[corner] = hits
    return out

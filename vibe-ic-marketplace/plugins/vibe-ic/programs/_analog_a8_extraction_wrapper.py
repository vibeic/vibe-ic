"""Lossless A8 interface adapter; the native extraction is never rewritten."""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import re
from typing import Dict, List, Tuple

from analog_a7_post_layout_emit import _joined_lines


def logical_lines(text: str) -> List[str]:
    # Reuse the RC producer's continuation parser, including indented '+'.
    return _joined_lines("\n".join(line.lstrip() for line in text.splitlines()))


def subckt_headers(text: str) -> Dict[str, List[str]]:
    """All complete headers; ngspice names are case insensitive."""
    headers: Dict[str, List[str]] = {}
    seen = set()
    active = None
    for line in logical_lines(text):
        tokens = line.split()
        if not tokens or tokens[0].startswith(("*", ";")):
            continue
        if tokens[0].lower() == ".subckt":
            if active is not None or len(tokens) < 3:
                raise ValueError("malformed/nested subckt header")
            name = tokens[1]
            if name.lower() in seen:
                raise ValueError("duplicate/ambiguous subckt name")
            seen.add(name.lower())
            headers[name] = tokens[2:]
            active = name
        elif tokens[0].lower() == ".ends":
            if active is None or (len(tokens) > 1 and
                                  tokens[1].lower() != active.lower()):
                raise ValueError("unmatched subckt end")
            active = None
    if active is not None:
        raise ValueError("unterminated subckt")
    return headers


def native_ports(text: str, block: str) -> List[str]:
    headers = subckt_headers(text)
    if block not in headers:
        raise ValueError(f"no exact declared top-cell .subckt {block!r}")
    ports = headers[block]
    _unique_nodes(ports)
    return ports


def _unique_nodes(nodes: List[str]) -> None:
    if (not nodes or any(not isinstance(n, str) or not n or
                        re.search(r"[\s=();\"'$]", n) or
                        n.lower() in ("0", "params:") for n in nodes)):
        raise ValueError("missing/unsupported port or node token")
    if len({n.lower() for n in nodes}) != len(nodes):
        raise ValueError("duplicate/ambiguous port or node")


def build_wrapper(raw: str, block: str, declared: List[str]
                  ) -> Tuple[str, Dict[str, object]]:
    """One native instance, with a positional bijection and no new circuitry.

    Each native RC terminal keeps a distinct node. Only terminals explicitly
    declared by A3 are exposed. Floating bulk remains floating inside this
    hierarchy; no alias or inferred supply connection is introduced.
    """
    _unique_nodes(declared)
    ports = native_ports(raw, block)
    names = subckt_headers(raw)
    wrapper = block + "__a8_interface"
    if (not re.fullmatch(r"[A-Za-z_][\w.+-]*", wrapper) or
            wrapper.lower() in {n.lower() for n in names}):
        raise ValueError("wrapper/native subckt name collision")
    globals_ = {t.lower() for line in logical_lines(raw)
                if line.lower().startswith(".global ")
                for t in line.split()[1:]}
    lookup = {p.lower(): p for p in declared}
    if not set(lookup).issubset({p.lower() for p in ports}):
        raise ValueError("missing declared port in native extraction")
    nodes = [lookup.get(p.lower(), f"a8_rc_p{i:04d}")
             for i, p in enumerate(ports)]
    _unique_nodes(nodes)
    if globals_.intersection(n.lower() for n in nodes) or globals_.intersection(
            p.lower() for p in ports):
        raise ValueError("global node collision prevents isolated mapping")
    # Small continued instance lines are accepted by the existing SPICE reader.
    instance = ["Xnative " + " ".join(nodes[:8])]
    instance += ["+ " + " ".join(nodes[i:i + 8])
                 for i in range(8, len(nodes), 8)]
    instance.append("+ " + block)
    text = "\n".join([
        "* A8 interface adapter; raw native extraction remains a separate file.",
        f".subckt {wrapper} {' '.join(declared)}", *instance,
        f".ends {wrapper}", ""])
    return text, {"native_subckt": block, "wrapper_subckt": wrapper,
                  "native_ports": ports, "instance_nodes": nodes}

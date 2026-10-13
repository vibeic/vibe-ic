#!/usr/bin/env python3
"""Which module in a REUSED-IP design's STAGED RTL is the one its documents
describe — and what does that module actually declare?

WHY THIS EXISTS
===============
Phase 1 reads ``input/docs/`` only. For a design whose input STAGES the
implementation (``input/vendor_rtl/``), the documents state the port NAMES and
the RTL states what those ports ARE. Neither alone is the answer, and Phase 1
was only ever asking one of them.

MEASURED on ``opentitan_aes`` (2026-09-02, plugin v1.15.50). The staged
``aes.sv`` declares 14 ports. ``L9_INTEGRATION_SPEC.json`` published 9 entries,
of which 7 were real ports and 2 (``tl`` / ``edn``) were Comportable
inter-signal BASE names the doc's own table lists, not ports at all. Missing
entirely: ``rst_ni``, ``rst_shadowed_ni``, ``rst_edn_ni``, ``tl_i``, ``tl_o``,
``alert_rx_i``, ``alert_tx_o`` — both resets and both alert ports. Downstream,
``professional_tb_gen`` emitted ``RST = None`` and a reset routine that does
nothing, and ``full_stack_tb_gen`` declared ``reg tl_i = 0;`` for a
100-plus-bit ``tlul_pkg::tl_h2d_t`` struct.

The doc-side width loss has one mechanism, and it is not a bug in the walker:
the Comportable *Inter-Module Signals* table's ``Width`` column means "one
instance of the struct", so ``| tl | tlul_pkg::tl | req_rsp | rsp | 1 |``
correctly reads as ``1`` — of a struct whose name the walker discards because
no L-doc field could hold it. A port's declared TYPE had nowhere to go.

HOW THE TOP MODULE IS CHOSEN — and why not the two obvious ways
===============================================================
Both structural shortcuts were measured on the corpus and both are WRONG:

  * *"the module nobody instantiates"* — over the staged aes tree that is 136
    of 243 modules, and ``aes`` is not among them (``aes_wrap`` instantiates
    it).
  * *"the module with the largest instantiation closure"* — that is
    ``aes_wrap`` (38 vs ``aes``'s 36), whose own first comment line reads
    "AES wrapper for FI experiments". A fault-injection harness is not the
    design, and publishing its ports (``aes_input`` / ``aes_key`` /
    ``test_done_o``) as the design's would be a fabricated interface.

The rule used instead is a RECONCILIATION, which is what the situation
actually is: the design's DOCUMENTS name the ports, so the staged module the
documents describe is the one that DECLARES those names. Score every staged
module by how many of the document-derived port names it declares; take the
strict unique maximum, and require at least ``MIN_NAME_OVERLAP`` of them.

Measured on the same tree: ``aes`` 7, ``prim_edn_req`` 4, ``aes_core`` 3,
``aes_wrap`` 1. On ibex: ``ibex_core`` 12, next 2.

FAIL-CLOSED IN EVERY DIRECTION. No staged RTL, no document-derived names, a
tie for the maximum, or an overlap below the floor → ``None``, and the caller
enriches nothing. A design we could not identify the top of earns no
statement about its interface.

WHAT IS AND IS NOT ASSERTED
===========================
This module reports what the RTL DECLARES. It does not resolve a struct's
width (``tlul_pkg::tl_h2d_t`` is a type name, not a number) and it does not
elaborate a parameterised range (``[NumAlerts-1:0]`` comes back as the
expression, with ``width`` unresolved). A consumer that needs a number must
say so; a consumer that needs to know the port is not a scalar now can.
"""
from __future__ import annotations

import sys
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_PROG_DIR = Path(__file__).resolve().parent
if str(_PROG_DIR) not in sys.path:
    sys.path.insert(0, str(_PROG_DIR))

#: Below this many shared port names the match is a coincidence, not an
#: identification. Two is the floor at which a module can no longer share its
#: overlap with the clock alone.
MIN_NAME_OVERLAP = 2

#: Stamped on every port this module contributes, so a reader of L9 can tell a
#: declared port from a document-scraped one without consulting the evidence.
EXTRACTION_STRATEGY = "staged_rtl_module_port_declaration_v1_15_51"


def _module_port_audit():
    """The shared SystemVerilog header parser, or None when unimportable."""
    try:
        import module_port_audit as _mpa  # noqa: WPS433
    except Exception:                     # noqa: BLE001 — fail-closed
        return None
    return _mpa


def scan_staged_modules(vendor_dir) -> Dict[str, Any]:
    """``{module_name: ModuleDef}`` over a staged RTL tree, or ``{}``.

    Uses ``module_port_audit.scan_rtl_directory`` — the tree's one real
    SystemVerilog header parser, which already handles ANSI and non-ANSI
    headers, parameter blocks, packed dimensions and package-qualified types.
    Re-implementing that here is exactly the duplication this file's sibling
    ``_rtl_fsm_extract`` was written to stop.
    """
    mpa = _module_port_audit()
    if mpa is None or vendor_dir is None:
        return {}
    try:
        path = Path(vendor_dir)
    except Exception:                     # noqa: BLE001
        return {}
    if not path.is_dir():
        return {}
    try:
        return mpa.scan_rtl_directory(path)
    except Exception:                     # noqa: BLE001 — a parse blow-up
        return {}                         # enriches nothing, breaks nothing


def resolve_top_module(modules: Dict[str, Any],
                       doc_port_names: Iterable[str]) -> Optional[str]:
    """The staged module the documents describe, or None.

    Strict unique maximum overlap with ``doc_port_names``, at or above
    ``MIN_NAME_OVERLAP``. A tie is not resolved — it is refused."""
    names = {str(n) for n in doc_port_names if n}
    if not names or not modules:
        return None
    scored: List[tuple] = []
    for mod_name, mod in modules.items():
        ports = getattr(mod, "ports", None)
        if not isinstance(ports, dict):
            continue
        scored.append((len(names & set(ports)), mod_name))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored[0][0]
    if best_score < MIN_NAME_OVERLAP:
        return None
    if len(scored) > 1 and scored[1][0] == best_score:
        return None                       # a tie identifies nothing
    return scored[0][1]


def declared_ports(modules: Dict[str, Any], top: str,
                   *, project=None) -> List[Dict[str, Any]]:
    """Every port ``top`` declares, in declaration order, as plain dicts.

    ``evidence`` is project-relative when ``project`` is given, so what lands
    in a published document is a path inside the design and not this host's."""
    mod = modules.get(top)
    ports = getattr(mod, "ports", None)
    if not isinstance(ports, dict):
        return []
    out: List[Dict[str, Any]] = []
    for port in ports.values():
        src = str(getattr(port, "file", "") or "")
        if project is not None and src:
            try:
                src = Path(src).resolve().relative_to(
                    Path(project).resolve()).as_posix()
            except Exception:             # noqa: BLE001 — keep what we have
                src = Path(src).name
        rec: Dict[str, Any] = {
            "name": str(getattr(port, "name", "") or ""),
            "direction": str(getattr(port, "direction", "") or ""),
            "data_type": str(getattr(port, "data_type", "") or ""),
            "width_expr": str(getattr(port, "width_expr", "") or ""),
            "line": getattr(port, "line", None),
            "source_file": src,
            "module": top,
        }
        width = getattr(port, "width", None)
        # `-1` is `module_port_audit`'s "declared, not resolvable" (a
        # parameterised range). It is not a width and must not be published
        # as one; the expression that produced it is carried instead.
        #
        # And a port declared of a USER TYPE with no packed range is ONE
        # INSTANCE OF THAT TYPE, of a width this module cannot know — the
        # parser's structural default of 1 is a scalar default, not a
        # measurement. Publishing it would repeat, from the RTL side, exactly
        # the `width: 1` that made a 100-plus-bit TL-UL request struct look
        # like a wire. The type name is the honest answer; the number is
        # withheld.
        _typed_instance = bool(rec["data_type"]) and not rec["width_expr"]
        if isinstance(width, int) and width > 0 and not _typed_instance:
            rec["width"] = width
        if rec["name"]:
            out.append(rec)
    return out


def staged_top_ports(project, vendor_dir,
                     doc_port_names: Iterable[str]) -> List[Dict[str, Any]]:
    """`declared_ports()` for the staged top module the documents describe, or
    `[]` — the whole reconciliation in one call."""
    modules = scan_staged_modules(vendor_dir)
    top = resolve_top_module(modules, doc_port_names)
    if top is None:
        return []
    return declared_ports(modules, top, project=project)


def bind_selected_interface(project: Path, content: dict, *,
                            include_synthesis_handoff: bool = True) -> dict:
    """Bind a delegated, declared reused-IP interface to its selected top.

    Reuse the existing protocol + original L3 illustrative-name authority.
    Keep document examples for pad-group evidence; only those names receive
    the existing absent-from-top label. Fixed ports, directions and known
    widths remain obligations. This does not verify the declaration's author.
    The Phase-1 producer sets ``include_synthesis_handoff=False`` because it
    runs before L19/Step 9: it can bind only the current staged RTL interface.
    Implementation readers retain the default and validate their current
    synthesis handoff.
    """
    from l9_rtl_pin_consistency_check import (_auto_derive_renamed_interfaces,
                                              _l3_fixed_port_name)
    from renamed_interface_derive import _rtl_top_ports

    project = Path(project)
    already_bound = "selected_interface_binding" in content

    def not_applicable(reason: str) -> dict:
        # First-time optional enrichment may be inapplicable. Once bound,
        # losing its current authority must not return the stale projection.
        if already_bound:
            raise ValueError(f"already-bound selected interface: {reason}")
        return content

    choice_path = project / "plugin_output/declaration.json"
    manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    try:
        choice = json.loads(choice_path.read_text())
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        return not_applicable(f"current declaration or reused-IP manifest unreadable: {exc}")
    if not isinstance(choice, dict) or not isinstance(manifest, dict):
        return not_applicable("current declaration and reused-IP manifest must be objects")
    if manifest.get("reused_ip") is not True:
        return not_applicable("current manifest no longer declares reused_ip=true")
    top = str(content.get("top_module") or "")
    if not choice.get("top_module"):
        return not_applicable("current declaration.top_module is missing")
    if choice["top_module"] != top:
        raise ValueError(f"selected top {choice['top_module']!r} differs from L9 {top!r}")
    selected = _rtl_top_ports(project, top)
    # A pad/implementation consumer can have only the selected synthesis
    # header. Phase 1 must not consume that later producer's contract.
    if include_synthesis_handoff:
        try:
            from phase3_one_shot_runner import pnr_input_netlist
            from lec_run import netlist_top_ports
            netlist, _note, _scan = pnr_input_netlist(project, top)
            parsed = netlist_top_ports(netlist.read_text(), top)
            if parsed:
                actual = []
                for direction, rng, name in parsed:
                    m = re.fullmatch(r"\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]", rng.strip())
                    width = (abs(int(m.group(1)) - int(m.group(2))) + 1 if m
                             else (1 if not rng.strip() else None))
                    actual.append({"name": name, "direction": direction, "width": width})
                selected = (str(netlist.relative_to(project)), actual)
        except OSError:
            pass
    if not selected:
        return not_applicable("current selected top interface is unavailable")
    source, actual = selected
    ports = content.get("top_ports") or content.get("ports") or []
    documented = {p["name"]: p for p in ports if isinstance(p, dict) and p.get("name")}
    implemented = {p["name"]: p for p in actual}
    old = set(documented) - set(implemented)
    new = set(implemented) - set(documented)
    groups = _auto_derive_renamed_interfaces(project, sorted(old), sorted(new),
                                            input_only=True)
    # A previously bound document must still be checked against current bytes.
    if not groups and not already_bound:
        return content
    retired = {n for g in groups for n in g["l9"]}
    added = {n for g in groups for n in g["rtl"]}
    if not groups:
        # Recompute authorization using the original document-side examples,
        # rather than trusting an old binding receipt to authorize new names.
        original = [n for n in old if documented[n].get("declared_by_staged_top") is False]
        rhs = [n for n, p in documented.items()
               if p.get("extraction_strategy") == EXTRACTION_STRATEGY]
        groups = _auto_derive_renamed_interfaces(project, original, rhs + sorted(new),
                                                input_only=True)
        retired = {n for g in groups for n in g["l9"]}
        added = {n for g in groups for n in g["rtl"]}
    missing = sorted(n for n in old if n not in retired
                     and documented[n].get("optional") is not True)
    fixed = sorted(n for n in retired if documented[n].get("required") is True
                   or documented[n].get("mandatory") is True
                   or _l3_fixed_port_name(project, n))
    unexpected = sorted(new - added)
    if missing or fixed or unexpected:
        raise ValueError(f"mandatory_missing={missing + fixed}; undeclared_ports={unexpected}")
    result = copy.deepcopy(content)
    bound = copy.deepcopy(ports)
    for port in bound:
        name = port.get("name")
        if name in retired:
            port["declared_by_staged_top"] = False
        elif name in implemented:
            rtl = implemented[name]
            direction = port.get("direction") or port.get("mode")
            width = port.get("width")
            if direction and direction != rtl["direction"]:
                raise ValueError(f"named direction mismatch for {name}: {direction} != {rtl['direction']}")
            if width is not None and rtl.get("width") is not None and width != rtl["width"]:
                raise ValueError(f"named width mismatch for {name}: {width} != {rtl['width']}")
            if width is None and isinstance(rtl.get("width"), int) and rtl["width"] > 0:
                port.update(width=rtl["width"], msb=rtl["width"] - 1, lsb=0)
            port["declared_by_staged_top"] = True
    for rtl in actual:
        if rtl["name"] not in new:
            continue
        width = rtl.get("width")
        if not isinstance(width, int) or width < 1:
            raise ValueError(f"selected width unresolved for {rtl['name']}")
        bound.append(dict(rtl, mode=rtl["direction"], io=None, rtl_name=rtl["name"],
                          aliases=[], msb=width - 1, lsb=0,
                          declared_by_staged_top=True,
                          extraction_strategy=EXTRACTION_STRATEGY))
    # Document evidence authorizes interface delegation, not the implemented
    # spelling or width. Keep that source's current subject/hash in the existing
    # implementation binding, which the pad consumer refreshes before reading.
    for port in bound:
        if (port.get("extraction_strategy") != EXTRACTION_STRATEGY
                or port["name"] not in added):
            continue
        citations = [documented[n].get("evidence") for g in groups
                     if port["name"] in g["rtl"] for n in g["l9"]
                     if documented[n].get("evidence")]
        if not citations:
            raise ValueError(f"input delegation evidence missing for {port['name']}")
        port["evidence"] = (
            "Input interface delegation: " + "; ".join(dict.fromkeys(map(str, citations)))
            + ". Implemented name/direction/width: selected_interface_binding "
              "(current selected_source and selected_source_sha256).")
    for key in ("ports", "top_ports", "top_module_pins"):
        result[key] = bound
    provenance_path = project / "plugin_output/declaration.provenance.json"
    result["selected_interface_binding"] = {
        "top_module": top, "declaration": "plugin_output/declaration.json",
        "declaration_sha256": hashlib.sha256(choice_path.read_bytes()).hexdigest(),
        "declaration_provenance": "plugin_output/declaration.provenance.json",
        "declaration_provenance_sha256": (hashlib.sha256(provenance_path.read_bytes()).hexdigest()
                                          if provenance_path.is_file() else None),
        "provenance_verification": "NOT_VERIFIED_BY_INTERFACE_BINDING",
        "selected_source": source,
        "selected_source_sha256": hashlib.sha256((project / source).read_bytes()).hexdigest(),
        "illustrative_groups": groups, "document_examples_not_implemented": sorted(retired),
    }
    return result



def selected_interface_ports(project: Path, content: dict) -> List[Dict[str, Any]]:
    """Return the current chosen roster without deleting document provenance.

    Binding labels alone do not retire a requirement. Re-run the existing
    input/declaration/top binding and the manifest's electrical obligations.
    This reader leaves the L9 document and every earlier output untouched.
    """
    rosters = [content[key] for key in ("ports", "top_ports", "top_module_pins")
               if key in content]
    if (not rosters or any(not isinstance(rows, list) or rows != rosters[0]
                           for rows in rosters)):
        raise ValueError("selected interface port rosters disagree")
    bound = bind_selected_interface(project, content)
    if "selected_interface_binding" not in bound:
        return rosters[0]
    from l9_rtl_pin_consistency_check import _manifest_renamed_groups
    manifest = json.loads((Path(project) / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text())
    declared = _manifest_renamed_groups(manifest)
    rows = {p["name"]: p for p in bound["ports"]}
    retired = set(bound["selected_interface_binding"]["document_examples_not_implemented"])
    for group in bound["selected_interface_binding"]["illustrative_groups"]:
        sources, targets = set(group["l9"]), set(group["rtl"])
        pairs = [(lhs, rhs) for lhs, rhs in declared
                 if lhs and rhs and lhs <= sources and rhs <= targets]
        if (set().union(*(lhs for lhs, _ in pairs)) != sources
                or set().union(*(rhs for _, rhs in pairs)) != targets):
            raise ValueError("selected interface rename is not declared in current manifest")
        # Authorization groups span a protocol family; electrical equivalence
        # belongs to each declared mapping, not every cross-family pair.
        for lhs, rhs in pairs:
            for source in lhs:
                for target in rhs:
                    old, new = rows[source], rows[target]
                    if (old.get("direction") or old.get("mode")) != new["direction"]:
                        raise ValueError(f"selected rename direction mismatch: {source} -> {target}")
                    if (isinstance(old.get("width"), int) and isinstance(new.get("width"), int)
                            and old["width"] != new["width"]):
                        raise ValueError(f"selected rename width mismatch: {source} -> {target}")
    return [port for port in bound["ports"] if port["name"] not in retired]


def refresh_selected_interface(project: Path, path: Path, content: dict, *,
                               include_synthesis_handoff: bool = True) -> dict:
    """Ordinary producer refresh for a continuation's existing L9 document."""
    bound = bind_selected_interface(
        project, content, include_synthesis_handoff=include_synthesis_handoff)
    if bound != content:
        from l_doc_generator_stamp import dump
        dump(path, bound, emitter="_staged_top_module.refresh_selected_interface")
    return bound

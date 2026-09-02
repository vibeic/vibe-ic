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

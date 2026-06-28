#!/usr/bin/env python3
"""spec_complete_extract.py — the GENERAL (benchmark-agnostic) complete-spec
extraction + completeness engine.

WHY (owner directive 2026-06-26): the per-record completeness machinery that drove
CVDP from 210→229 COMPLETE is GENERAL — it parses Verilog/SystemVerilog SPEC PROSE
(widths, register maps, FSMs, enum sets, numeric packing, worked examples, reset
semantics, timing) and rolls every port into a COMPLETE / EXTRACTION_GAP /
SPEC_ABSENT verdict. None of that is CVDP-specific. The only CVDP-specific part is
RECOVERING THE INTERFACE from a CVDP record (its cocotb `dut.<sig>` harness + .env
TOPLEVEL + skeleton header). So the benchmark-convergence work BENEFITS GENERAL
PHASE-1 INPUT once the engine is callable with a plainly-supplied interface.

This module is that general engine. `cvdp_complete_extract` (and any future
VerilogEval / RTLLM / Phase-1 caller) becomes a THIN ADAPTER: recover the interface
in whatever way that source provides it, then call `assess_spec(...)`.

DESIGN — the interface signal set is an INPUT, not read from a harness:
  * CVDP adapter:    inputs/outputs = the cocotb `dut.<sig>` driven/read sets.
  * Phase-1 / doc:   inputs/outputs = the port list the L-docs / prose state.
  * VerilogEval:     inputs/outputs = the prose `### Inputs/Outputs` port list.
The cocotb harness TEXT (`tb`) is an OPTIONAL interface oracle (it pins a port to
1-bit when it drives {0,1}); when absent (`tb=""`) the engine relies on the prose
width forms + the universal clk/rst/1-bit naming convention + the param table.

§4.05 NO-LEAK / NO-CHEAT (inherited from the proven helpers): every emitted field
is anchored to a real structural source in the prose / supplied interface; a width
is resolved only from a stated form or a recognised parameter; an unresolved DATA
width is recorded as an honest gap, never fabricated.

The structural helpers themselves are the already-shipped, individually-tested
general extractors (`verilog_width_resolve`, `spec_{regmap,fsm,enumset,numeric_pack,
worked_example}_extract`) plus the width/reset/timing/one-bit readers. To avoid
duplicating ~800 proven lines, this engine IMPORTS those helpers from
`cvdp_complete_extract` (which is being thinned to an adapter over THIS module); the
helpers operate purely on strings, so the import carries no record coupling.

chip-AGNOSTIC: every decision keys on STRUCTURE + generic vocabulary, never on a
design name, a problem id, a dataset, or a SKU literal.

Public API
    assess_spec(prompt, inputs, outputs, *, module_name="", skeleton_iface=None,
                param_defaults=None, table=None, tb="", record_id=None) -> dict
        same shape as the old cvdp extract() spec dict (interface / structures /
        reset / timing / params / completeness / completeness_reason / gaps), but
        the interface is SUPPLIED, not recovered from a record.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The proven general helpers live in cvdp_complete_extract (being thinned to an
# adapter over THIS engine). They are pure-string functions — no record coupling.
import cvdp_complete_extract as _impl  # noqa: E402
import verilog_width_resolve as _W  # noqa: E402


def _place_interface(prompt: str, inputs: List[str], outputs: List[str],
                     params: set, param_defaults: Dict[str, int],
                     table: Dict[str, int], ctx_widths: Dict[str, int],
                     tb: str) -> Tuple[List[dict], List[dict]]:
    """The GENERAL port-placement + gap-classification core (extracted verbatim
    from the proven `_complete_interface` body): for each interface signal, resolve
    its width from prose / param-expression / context header / clk-rst-1bit
    convention / harness 1-bit pin, else record an honest width gap. Returns
    (interface, gaps). Pure over the SUPPLIED interface — no record access."""
    import re
    signed = bool(re.search(
        r"(?i)\bsigned\b|two'?s?\s+complement|2'?s?\s+complement", prompt))
    config_params = set(params) | set(param_defaults) | set(
        re.findall(r"\bparameter\b\s+(?:\w+\s+)?([A-Za-z_]\w*)", prompt))
    iface: List[dict] = []
    gaps: List[dict] = []

    def _place(name: str, direction: str):
        if name in params or name in param_defaults:
            return  # a config parameter — not a port
        w, src = _impl._resolve_width(prompt, table, name, param_defaults)
        if w is not None:
            iface.append({"name": name, "dir": direction, "width": w,
                          "signed": signed, "source": src})
            return
        if name in ctx_widths:
            iface.append({"name": name, "dir": direction, "width": ctx_widths[name],
                          "signed": signed, "source": "context_header"})
            return
        if src == "param_expression_width":
            iface.append({"name": name, "dir": direction, "width": None,
                          "signed": signed, "source": "param_expression_width"})
            idents = _W.param_expr_idents(prompt, name)
            if idents and idents <= config_params:
                return  # PARAMETERISED-COMPLETE
            gaps.append({"kind": "INCOMPLETE_EXTRACTION_GAP",
                         "type": "param_expression_width",
                         "detail": f"{direction} port `{name}` width is a parameter "
                                   f"expression with no resolvable default",
                         "evidence": _impl._evidence_line(prompt, name)})
            return
        if _impl._is_clk(name) or _impl._is_rst(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "clk_rst_convention"})
            return
        # §3.9 HARNESS-as-source: the cocotb test drives this port with values
        # provably in {0,1} -> it is a 1-bit port pinned by the harness interface,
        # not a spec-absent fact. Check BEFORE the generic 1-bit naming convention
        # so the source tag reflects the STRONGER harness evidence (e.g. `serial_in`
        # driven by `random.randint(0,1)` is credited to the harness, not just the
        # name containing `serial`).
        if _impl._harness_one_bit(tb, name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "harness_one_bit"})
            return
        if _impl._ONE_BIT_RE.match(name):
            iface.append({"name": name, "dir": direction, "width": 1,
                          "signed": False, "source": "one_bit_convention"})
            return
        gkind, gtype = _impl._classify_width_gap(prompt, name, params, param_defaults)
        gaps.append({"kind": gkind, "type": gtype,
                     "detail": f"{direction} port `{name}` width unresolved",
                     "evidence": _impl._evidence_line(prompt, name)})

    for n in inputs:
        _place(n, "input")
    for n in outputs:
        _place(n, "output")
    # de-dup by name (a signal read AND written keeps first dir)
    seen, dedup = set(), []
    for p in iface:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        dedup.append(p)
    return dedup, gaps


def _verdict(iface: List[dict], inputs: List[str], outputs: List[str],
             gaps: List[dict], have_oracle: bool) -> Tuple[str, str]:
    """Roll per-signal gaps into ONE completeness verdict (general; extracted from
    the proven `_completeness`). `have_oracle` is True when SOME interface source
    was present (a harness or a supplied port list) — distinguishes 'no interface
    to bind' (SPEC_ABSENT) from 'interface present but a width missed' (GAP)."""
    has_ext = any(g["kind"] == "INCOMPLETE_EXTRACTION_GAP" for g in gaps)
    has_abs = any(g["kind"] == "INCOMPLETE_SPEC_ABSENT" for g in gaps)
    if not inputs and not outputs and not iface:
        if not have_oracle:
            return "INCOMPLETE_SPEC_ABSENT", "no interface source to bind the ports"
        return ("INCOMPLETE_EXTRACTION_GAP",
                "interface source present but no port recovered")
    if has_ext:
        types = sorted({g["type"] for g in gaps
                        if g["kind"] == "INCOMPLETE_EXTRACTION_GAP"})
        return "INCOMPLETE_EXTRACTION_GAP", "missed fact(s): " + ", ".join(types)
    if has_abs:
        types = sorted({g["type"] for g in gaps
                        if g["kind"] == "INCOMPLETE_SPEC_ABSENT"})
        return ("INCOMPLETE_SPEC_ABSENT",
                "fact(s) absent from prompt prose + interface + convention: "
                + ", ".join(types))
    return ("COMPLETE",
            "every port placed (prose/param-expr/interface); stated structures captured")


def assess_spec(prompt: str, inputs: List[str], outputs: List[str], *,
                module_name: str = "", skeleton_iface: Optional[List[dict]] = None,
                param_defaults: Optional[Dict[str, int]] = None,
                table: Optional[Dict[str, int]] = None, tb: str = "",
                params: Optional[set] = None,
                ctx_widths: Optional[Dict[str, int]] = None,
                record_id=None) -> dict:
    """GENERAL completeness assessment over a SUPPLIED interface.

    prompt          — the design-doc / spec prose (any benchmark or Phase-1 doc).
    inputs/outputs  — the interface signal NAMES (however the caller obtained them:
                      cocotb dut.<sig>, an L-doc port list, prose ### Inputs/Outputs).
    skeleton_iface  — OPTIONAL fully-described port list [{name,dir,width,...}] (a
                      module header); when given it is the interface verbatim and
                      port placement is skipped (nothing to resolve).
    param_defaults  — OPTIONAL NAME->int param table; default: parsed from `prompt`.
    table           — OPTIONAL test-case hex-column width table; default: {}.
    tb              — OPTIONAL cocotb harness text (the 1-bit {0,1}-drive oracle).
    params          — OPTIONAL recognised config-parameter set (harness-driven).
    ctx_widths      — OPTIONAL name->width from a provided context module header.

    Returns the spec dict (same shape as the historical cvdp extract())."""
    if param_defaults is None:
        param_defaults = _W.param_defaults(prompt, tb)
    if table is None:
        table = {}
    if params is None:
        params = set()
    if ctx_widths is None:
        ctx_widths = {}

    structures = _impl._structures(prompt)
    timing = _impl._timing(prompt)

    if skeleton_iface is not None:
        iface = skeleton_iface
        gaps: List[dict] = []
    else:
        iface, gaps = _place_interface(
            prompt, inputs, outputs, params, param_defaults, table, ctx_widths, tb)

    have_oracle = bool(inputs or outputs or skeleton_iface or tb)
    completeness, reason = _verdict(iface, inputs, outputs, gaps, have_oracle)

    return {
        "id": record_id,
        "module_name": module_name or None,
        "interface": iface,
        "operation_family": _impl._operation_family(prompt),
        "params": _impl._prompt_params(prompt),
        "structures": structures,
        "reset": _impl._reset_semantics(prompt, inputs),
        "timing": timing,
        "byte_order": _impl._byte_order(prompt),
        "completeness": completeness,
        "completeness_reason": reason,
        "gaps": gaps,
        "interface_source": {
            "module_name": module_name or None,
            "inputs": list(inputs),
            "outputs": list(outputs),
            "params": sorted(params),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: assess a single design-doc file with an explicitly-supplied port list.
    For benchmark jsonl distributions, use the per-benchmark adapter's CLI (e.g.
    `cvdp_complete_extract.py --jsonl ...`)."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True, help="a design-doc / spec prose file")
    ap.add_argument("--inputs", default="", help="comma-separated input port names")
    ap.add_argument("--outputs", default="", help="comma-separated output port names")
    ap.add_argument("--json", default=None, help="write the spec dict here")
    a = ap.parse_args(argv)
    import json
    prompt = open(a.doc).read()
    ins = [s.strip() for s in a.inputs.split(",") if s.strip()]
    outs = [s.strip() for s in a.outputs.split(",") if s.strip()]
    spec = assess_spec(prompt, ins, outs)
    out = json.dumps(spec, indent=2, ensure_ascii=False)
    if a.json:
        open(a.json, "w").write(out + "\n")
    print(f"completeness: {spec['completeness']}")
    print(f"reason: {spec['completeness_reason']}")
    if spec["gaps"]:
        print("gaps:")
        for g in spec["gaps"]:
            print(f"  {g['kind']} {g['type']}: {g['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

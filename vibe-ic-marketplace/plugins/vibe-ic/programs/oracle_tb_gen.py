#!/usr/bin/env python3
"""oracle_tb_gen.py — deterministic per-IC oracle testbench generator
(ORGANIC-20260606 #439).

The audited gap: only the AID class had a real reference TB; every
other class got (at best) a connectivity skeleton — toggle clk/reset,
0 bytes exchanged, functional_verified=false — so 3 of 4 campaign ICs
shipped with ZERO functional verification. TB generation is now a
FIRST-CLASS contract mirroring rtl_gen:

  * registry `tb_gen: oracle_tb_gen.py` → THIS deterministic generator;
  * when no concrete golden vectors are derivable, it exits 2 with the
    `tb_fallback_skill: testbench-gen` direction (the AI authors a
    per-IC oracle TB from L3/L5/L10, exactly as spec-to-rtl authors
    RTL), so a missing oracle is a NAMED open item, never a silent
    skeleton-PASS.

What it generates (when it can): `sim_full_stack/tb_<top>_oracle.v`
driving each concrete L10 vector against the L9 top — apply the input
values, wait, compare every expected output with `===`, print
per-vector PASS/FAIL and the final `ORACLE_TB_DONE pass=<n>/<m>`
marker the runner's functional gate parses. A manifest
(`oracle_manifest.json`) records vector provenance.

Concrete-vector shapes accepted in L10 test_cases[] (chip-AGNOSTIC —
structural keys, no chip names):
  {"inputs": {"<port>": <int|"0x..">}, "expected": {"<port>": <val>}}
  {"stimulus": {...},                  "expected_outputs": {...}}

Exit codes: 0 = TB emitted; 2 = no concrete vectors → fallback-skill
direction printed as JSON; 1 = error.

testbench-gen CONTRACT — $readmem mem-file staging (ORGANIC #476):
  The runner compiles + runs the oracle TB with cwd =
  sim_full_stack/oracle_run/ (so oracle.vvp / oracle.log artifacts are
  collected there). If a hand-authored oracle TB loads firmware / ROM via
  `$readmemh("fw.hex", mem)` / `$readmemb(...)`, the bare/relative path is
  resolved at SIM TIME against that run cwd — NOT against the TB source
  directory. To keep author intent natural, the runner stages every
  $readmem{h,b}-referenced data file that resolves relative to the TB's own
  directory into the run cwd before vvp runs (see
  design_one_shot_runner._stage_readmem_files). Author guidance: reference
  the hex by a path relative to the TB (place fw.hex next to
  tb_<top>_oracle.v, then write `$readmemh("fw.hex", mem)`); do NOT hard-code
  an absolute host path. Sub-directory refs (e.g. "rom/fw.hex") are staged
  preserving that sub-path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

_CLK_NAMES = {"clk", "clock", "clk_i", "i_clk", "sysclk"}
_RST_NAMES = {"rst", "reset", "rst_n", "reset_n", "rstn", "i_rst",
              "rst_ni", "arst_n"}


def _to_int(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().lower().replace("_", "")
        try:
            if s.startswith("0x"):
                return int(s, 16)
            if s.startswith("0b"):
                return int(s, 2)
            return int(s, 10)
        except ValueError:
            return None
    return None


def _load_top_ports(project: Path):
    """(top_name, [{name, dir, width}]) from L9, else (None, [])."""
    for cand in ("L9_INTEGRATION_SPEC.json", "L9.json"):
        p = _pl.generated_docs_dir(project) / cand
        if not p.is_file():
            p = project / "phase1" / "generated_docs" / cand
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        fields = d.get("fields", d)
        ports = fields.get("top_ports") or d.get("top_ports") or []
        top = (fields.get("top_module") or d.get("top_module")
               or "chip_top")
        norm = []
        for q in ports:
            if not isinstance(q, dict) or not q.get("name"):
                continue
            direction = str(q.get("dir") or q.get("direction") or "").lower()
            width = q.get("width") or 1
            try:
                width = int(width)
            except (TypeError, ValueError):
                width = 1
            norm.append({"name": q["name"],
                         "dir": "output" if direction.startswith("o")
                         else "input",
                         "width": max(1, width)})
        if norm:
            return top, norm
    return None, []


def _load_concrete_vectors(project: Path):
    l10 = project / "phase1" / "generated_docs" / "L10_TEST_CASES.json"
    try:
        d = json.loads(l10.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    cases = (d.get("test_cases")
             or d.get("fields", {}).get("test_cases") or [])
    vectors = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        ins = c.get("inputs") or c.get("stimulus")
        outs = c.get("expected") or c.get("expected_outputs")
        if not isinstance(ins, dict) or not isinstance(outs, dict):
            continue
        ins_n = {k: _to_int(v) for k, v in ins.items()}
        outs_n = {k: _to_int(v) for k, v in outs.items()}
        if (any(v is None for v in ins_n.values())
                or any(v is None for v in outs_n.values()) or not outs_n):
            continue  # non-numeric / no golden — not a concrete vector
        vectors.append({"name": c.get("name") or c.get("id")
                        or f"vec{len(vectors)}",
                        "inputs": ins_n, "expected": outs_n})
    return vectors


def generate(project: Path):
    """Returns (verdict_dict, exit_code)."""
    top, ports = _load_top_ports(project)
    vectors = _load_concrete_vectors(project)
    pnames = {p["name"] for p in ports}
    usable = [v for v in vectors
              if set(v["inputs"]) <= pnames and set(v["expected"]) <= pnames]
    if not ports or not usable:
        return ({
            "program": "oracle_tb_gen",
            "verdict": "SKIPPED-CONDITION",
            "fallback_skill": "testbench-gen",
            "reason": ("no concrete golden vectors derivable from L10 "
                       "against the L9 top ports — AI invokes skill "
                       "testbench-gen: author a per-IC oracle TB from "
                       "L3/L5/L10 at sim_full_stack/tb_<top>_oracle.v "
                       "(#439); a skeleton TB is NOT functional "
                       "verification"),
            "top_ports_found": len(ports),
            "l10_vectors_found": len(vectors),
            "usable_vectors": len(usable),
        }, 2)

    clk = next((p["name"] for p in ports
                if p["dir"] == "input" and p["name"].lower() in _CLK_NAMES),
               None)
    rst = next((p["name"] for p in ports
                if p["dir"] == "input" and p["name"].lower() in _RST_NAMES),
               None)
    rst_active_low = bool(rst) and rst.lower().rstrip("i").endswith("n")

    lines = ["`timescale 1ns/1ps",
             f"// Auto-generated by oracle_tb_gen (#439) — per-IC oracle TB",
             f"// vectors: {len(usable)} concrete golden vector(s) from L10",
             f"module tb_{top}_oracle;"]
    for p in ports:
        decl = "reg" if p["dir"] == "input" else "wire"
        rng = f" [{p['width'] - 1}:0]" if p["width"] > 1 else ""
        lines.append(f"  {decl}{rng} {p['name']};")
    conns = ", ".join(f".{p['name']}({p['name']})" for p in ports)
    lines.append(f"  {top} dut ({conns});")
    if clk:
        lines.append(f"  initial {clk} = 1'b0;")
        lines.append(f"  always #5 {clk} = ~{clk};")
    lines.append("  integer _pass; integer _total;")
    lines.append("  initial begin")
    lines.append("    _pass = 0; _total = 0;")
    if rst:
        lines.append(f"    {rst} = 1'b{'0' if rst_active_low else '1'};")
        lines.append("    #40;")
        lines.append(f"    {rst} = 1'b{'1' if rst_active_low else '0'};")
        lines.append("    #20;")
    for v in usable:
        lines.append(f"    // vector: {v['name']}")
        for k, val in v["inputs"].items():
            lines.append(f"    {k} = {val};")
        lines.append("    #100;")
        lines.append("    _total = _total + 1;")
        checks = " && ".join(f"({k} === {val})"
                             for k, val in v["expected"].items())
        exp_disp = ", ".join(f"{k}={val}" for k, val in v["expected"].items())
        lines.append(f"    if ({checks}) begin")
        lines.append(f"      _pass = _pass + 1;")
        lines.append(f"      $display(\"ORACLE_VECTOR {v['name']} PASS\");")
        lines.append("    end else begin")
        lines.append(f"      $display(\"ORACLE_VECTOR {v['name']} FAIL "
                     f"(expected {exp_disp})\");")
        lines.append("    end")
    lines.append("    $display(\"ORACLE_TB_DONE pass=%0d/%0d\", _pass, _total);")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")

    sim_dir = _pl.sim_full_stack_dir(project)
    sim_dir.mkdir(parents=True, exist_ok=True)
    tb_path = sim_dir / f"tb_{top}_oracle.v"
    tb_path.write_text("\n".join(lines) + "\n")
    manifest = {
        "program": "oracle_tb_gen",
        "verdict": "TB_EMITTED",
        "tb": str(tb_path.relative_to(project)),
        "top": top,
        "vectors": [v["name"] for v in usable],
        "vector_count": len(usable),
        "source": "phase1/generated_docs/L10_TEST_CASES.json",
    }
    (sim_dir / "oracle_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    rep, rc = generate(args.project.resolve())
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())

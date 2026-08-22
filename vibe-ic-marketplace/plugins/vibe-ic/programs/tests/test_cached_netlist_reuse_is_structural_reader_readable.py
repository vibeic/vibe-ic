"""The netlist repair guarded the path the runner had just inspected, and not
the one it had not.

The defect
----------
`step_synth` has normalised its own yosys output since v1.6.605: OpenROAD's
STRUCTURAL Verilog reader rejects the `signed` qualifier in a net declaration,
so the runner strips it right after `write_verilog` and PnR can read the file.

`main()` does not always call `step_synth`. When `<synth>/<top>_synth.v`
already exists the runner takes the preserve-provenance REUSE branch, whose
three tests all ask the same question — is this netlist CURRENT?

    * `_netlist_matches_liberty`   — mapped to the ACTIVE PDK?
    * `_stale_rtl_by_fingerprint`  — synthesised from the CURRENT RTL?
    * `_stale_rtl_vs_netlist`      — older than its RTL?

None of them asks whether the file is one the CONSUMER can read. So a cached
netlist that is current in every respect and unreadable by OpenROAD went
straight to `step_pnr`, which died in `link_design`.

Measured, on a 1,356,810-instance nangate45 netlist left by an earlier run:

    grep -c 'wire signed' <top>_synth.v                       ->  40771
    openroad -exit pnr.tcl
      [ERROR STA-0171] .../<top>_synth.v line 1293425, syntax error
      Error: pnr.tcl, 8 STA-0171
    phase3/stage3/pnr/openroad.log                            ->  927 bytes

and the run reported `BLOCKED pnr` after 20 minutes with a DEF older than its
own launch. The netlist was complete and correctly mapped; one keyword made it
unreadable.

Bidirectional control against the real reader (OpenROAD 26Q3-1066-g29e3e63e45,
nangate45 tech LEF + cell LEF + Liberty), same file with and without the
qualifier:

    wire signed [3:0] \\u.k[0] ;   ->  [ERROR STA-0171] line 6, syntax error
    wire [3:0] \\u.k[0] ;          ->  LINK_OK_PLAIN

The fix
-------
ONE helper, `_ensure_structural_reader_readable`, called from BOTH paths that
put a file at the path `step_pnr` reads: the produce path (`step_synth`) and
the reuse path (`main`). Because the reuse path rewrites bytes a provenance
record already declares, the helper restamps that record with the REAL new
sha256 via `_restamp_provenance_output` — the contract the runner already uses
wherever it re-emits a declared output — so the repair cannot leave a
PROVENANCE_HASH_MISMATCH behind.

What this test pins
-------------------
1. the helper strips the qualifier and leaves an escaped identifier that merely
   CONTAINS `signed` alone (negative control);
2. it is a no-op on an already-clean netlist (idempotence);
3. it restamps the declaring provenance entry to the REAL post-repair digest;
4. `main`'s reuse branch CALLS it — the source-level assertion, because the
   defect was never in the helper, it was in which paths reach it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as _runner                    # noqa: E402

_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")

_NETLIST_WITH_SIGNED = """module t (a, z);
  input a;
  wire a;
  output z;
  wire z;
  wire signed [3:0] \\u_core.a_h[0] ;
  reg signed [31:0] k;
  wire [7:0] \\bus_signed ;
  BUF_X1 b0 (.A(a), .Z(z));
endmodule
"""


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _project(tmp_path: Path) -> tuple:
    nl = tmp_path / "t_synth.v"
    nl.write_text(_NETLIST_WITH_SIGNED)
    prov = tmp_path / "provenance.jsonl"
    prov.write_text(json.dumps({
        "tool": "yosys",
        "command": "yosys -p 'synth'",
        "exit_code": 0,
        "timestamp": "2026-01-01T00:00:00Z",
        "outputs": {"t_synth.v": _sha(nl)},
    }) + "\n")
    return nl, prov


def test_qualifier_is_stripped_and_a_name_containing_signed_is_not(tmp_path):
    nl, _ = _project(tmp_path)
    n = _runner._ensure_structural_reader_readable(nl, tmp_path)
    body = nl.read_text()
    assert n == 2, f"expected both declarations repaired, got {n}"
    assert "wire [3:0] \\u_core.a_h[0] ;" in body, body
    assert "reg [31:0] k;" in body, body
    # NEGATIVE CONTROL: an escaped identifier that merely contains the token.
    assert "\\bus_signed" in body, (
        "an escaped identifier containing 'signed' was mangled; the qualifier "
        "must stand alone after the declaration keyword/range")
    assert " signed " not in body and " signed[" not in body, body


def test_repair_is_idempotent_on_an_already_clean_netlist(tmp_path):
    nl, _ = _project(tmp_path)
    _runner._ensure_structural_reader_readable(nl, tmp_path)
    before = nl.read_bytes()
    again = _runner._ensure_structural_reader_readable(nl, tmp_path)
    assert again == 0
    assert nl.read_bytes() == before, "a clean netlist must not be rewritten"


def test_repair_restamps_the_declaring_provenance_entry(tmp_path):
    nl, prov = _project(tmp_path)
    stale = json.loads(prov.read_text().splitlines()[0])["outputs"]["t_synth.v"]
    _runner._ensure_structural_reader_readable(nl, tmp_path)
    rows = [json.loads(l) for l in prov.read_text().splitlines() if l.strip()]
    declared = [r["outputs"]["t_synth.v"] for r in rows
                if "t_synth.v" in r.get("outputs", {})]
    assert declared, "the netlist lost its provenance declaration entirely"
    # The repair APPENDS a record of the bytes it produced rather than
    # amending the stale one, so the stale digest survives as history. What
    # must hold is that the NEWEST declaration — the one the gate verifies
    # against disk — carries the digest the file actually has.
    assert declared[-1] == _sha(nl), (
        "the repaired netlist is still declared under a digest it no longer "
        f"carries: newest={declared[-1]} real={_sha(nl)}")
    assert declared[-1] != stale


def test_the_reuse_branch_calls_the_same_helper_as_the_produce_path():
    """The defect was never in the helper — it was in which paths reach it."""
    calls = _SRC.count("_ensure_structural_reader_readable(")
    assert calls >= 3, (
        "expected the definition plus BOTH call sites (step_synth's produce "
        f"path and main()'s preserve-provenance reuse path); found {calls}")
    tree = ast.parse(_SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_ensure_structural_reader_readable" in called, (
        "main()'s preserve-provenance reuse branch hands step_pnr a netlist "
        "it never normalised; the guard covers only the netlist the runner "
        "just produced")
    fn_synth = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "step_synth")
    called_synth = {
        n.func.id for n in ast.walk(fn_synth)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_ensure_structural_reader_readable" in called_synth, (
        "the produce path stopped using the shared helper")

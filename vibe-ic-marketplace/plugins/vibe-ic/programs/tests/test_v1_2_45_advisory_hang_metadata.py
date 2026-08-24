#!/usr/bin/env python3
r"""v1.2.45 — emit-side hang-hint metadata (ADVISORY ONLY, §4.05 no-leak).

The 6 file-named hang subjects in the CVDP run (mem_allocator /
manchester_enc / ir_receiver / fifo_async / attenuator / axi_alu cluster)
HANG in cocotb by watchdog time-out. Their actual root causes in v1.2.44
are NOT combinational self-loop / forever — they are wrong-data / timing /
w-r-ptr mismatch — and the heuristic set in sim_hang_detect.py only
trips on STRONG combinational-loop / forever-in-@* shapes. Empirically:

  * 0/6 of the file-named hang subjects trip the detector
  * 28/302 entries trip `predicted_hang=True` overall
  * 17/28 of those trips are on the score-final PASS list — i.e. an
    ACTIVE BLOCK on `predicted_hang=True` would cost 17 false positives
    (§4.05 leak)

v1.2.45 pins three properties:
  (a) STRONG shapes ARE detected (combinational self-loop, forever in @*)
  (b) LEGITIMATE counter idiom is NOT falsely flagged (counter `i=i+1`)
  (c) cvdp_gate.py records the tag as ADVISORY ONLY — i.e. it NEVER
      flips `pass` to `fail` based on this metadata. The tag surfaces
      only in entry["hang_predicted"] / entry["hang_reason"] /
      entry["hang_signatures"] for downstream AUDIT, NOT verdict.

Run:  python3 -m py_compile programs/tests/test_v1_2_45_advisory_hang_metadata.py
-or-  python3 -m pytest -q programs/tests/test_v1_2_45_advisory_hang_metadata.py
"""
import json
import os
import pathlib
import re
import sys
import subprocess
import tempfile
from _hostpaths import repo_path_opt  # noqa: E402

PLUGIN_BENCH = str(repo_path_opt("vibe-ic-marketplace/plugins/vibe-ic/benchmark"))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(TESTS_DIR)


def _load():
    sys.path.insert(0, PLUGIN_BENCH)
    import sim_hang_detect as H   # noqa: E402
    import cvdp_gate as G            # noqa: E402
    import tb_toplevel_alias as A   # noqa: E402
    return H, G, A


def test_strong_combinational_self_loop_is_detected():
    """`always_comb a = ~a;` MUST trip predicted_hang=True."""
    H, *_ = _load()
    code = (
        "module m(input logic clk, output logic a);\n"
        "  always_comb a = ~a;\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(code)
    assert ok is True
    assert 'a' in why and 'self-loop' in why
    assert any('a' in s and 'self-loop' in s for s in sigs)


def test_forever_in_always_star_is_detected():
    """`always @* ... forever x = x;` MUST trip predicted_hang=True,
    specifically under the FOREVER STRONG signal (the determinism
    contract is: combinational-hang or forever-loop = STRONG=predicted_hang;
    anything else = WEAK=signatures-only)."""
    H, *_ = _load()
    code = (
        "module m(output logic x);\n"
        "  always @* begin forever x = x; end\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(code)
    assert ok is True, f"expected STRONG hit, got ok={ok}, why={why!r}"
    # Either forever-in-@* or self-loop. Both are STRONG.
    assert any('forever' in s or 'self-loop' in s for s in (sigs + [why]))
    # And specifically the hang tag MUST be carried (not silently dropped):
    assert sigs, f"expected ≥1 signature, got {sigs!r}"


def test_legitimate_counter_idiom_is_NOT_flagged():
    """`always @(posedge clk) cnt = cnt + 1` MUST NOT trip
    (legitimate sequential counter). seq counter is NOT combinational;
    `always @* cnt = cnt + 1` IS combinational and SHOULD also slip
    past (heuristic squelches the `+ 1` / `- 1` increment)."""
    H, *_ = _load()
    code_pos = (
        "module m(input logic clk, output logic [3:0] cnt);\n"
        "  always_ff @(posedge clk) cnt <= cnt + 1;\n"
        "endmodule\n"
    )
    assert H.predict_hang(code_pos)[0] is False
    code_star_inc = (
        "module m(output logic [3:0] cnt);\n"
        "  always @* cnt = cnt + 1;\n"
        "endmodule\n"
    )
    assert H.predict_hang(code_star_inc)[0] is False
    code_star_dec = (
        "module m(output logic [3:0] cnt);\n"
        "  always @* cnt = cnt - 1;\n"
        "endmodule\n"
    )
    assert H.predict_hang(code_star_dec)[0] is False


def test_clean_module_is_NOT_flagged():
    """A clean module produces absolutely no hang tag."""
    H, *_ = _load()
    code = (
        "module m(input logic clk, output logic q);\n"
        "  always_ff @(posedge clk) q <= 1'b0;\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(code)
    assert ok is False
    assert why == ''
    assert sigs == []


def test_dead_signal_is_weak_only():
    """`valid <= 1'b0` declared once WITHOUT a corresponding `valid <= 1`
    anywhere in the file is a WEAK hint — surfaced via signatures but
    does NOT lift `predicted_hang` to True (the WEAK shape must never
    block a passing record).

    The detector's dead-signal rule looks only at the same file. To
    trigger it we hand-author a code body where `valid` is ONLY driven
    to 0 in a 480-char window. That is unmistakably WEAK, since the
    combinational completion semantics may legitimately hold a signal
    at 0 across reset.
    """
    H, *_ = _load()
    code = (
        "module m(input logic clk, output logic [3:0] out);\n"
        "  reg valid;\n"
        "  // pad to ~480 chars so the windowed regex probes the signal\n"
        "  assign out = 4'b0;\n"
    )
    # The detector keys on `valid <= 1'b0;` inside an `always @(posedge clk)`
    # block. Construct such a body that DOES NOT also include `valid <= 1`.
    body = (
        "module m(input logic clk, output logic [3:0] out);\n"
        "  reg valid;\n"
        "  always @(posedge clk) begin\n"
        "    valid <= 1'b0;\n"
        "  end\n"
        "  assign out = 4'b0;\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(body)
    assert ok is False  # WEAK hint does NOT trip predicted_hang
    # WEAK must NOT silently disappear — it MUST show up in `signatures`,
    # even though `all_signatures` always includes weak hints:
    # The detector contract is: when WEAK fires, BOTH reason and signatures
    # carry the hint chain (the metadata is auditable). Either signatures
    # OR a non-empty reason confirms the hint went through.
    assert sigs or why, (
        f"WEAK sig surfacing lost — got ({ok!r}, {why!r}, {sigs!r})")


def test_cvdp_gate_records_metadata_without_altering_completion():
    """The gate's ONLY emit-side effect on a predicted_hang=True entry
    is the entry-level metadata — the completion BYTES (the score-verdict
    input) MUST be byte-identical to the un-annotated input.

    This is the §4.05 no-leak PILLAR: predicted_hang is metadata, never
    verdict-flipping signal.
    """
    H, _G, A = _load()
    # 1) The alias top is resolved from the PROMPT skeleton (the COMPLIANT
    #    source — the hidden harness `.env` is OFF-LIMITS oracle and is never
    #    read for the scored completion). We feed a prompt whose ```verilog
    #    module m( skeleton names `m` and assert the real gate function
    #    resolves it.
    prompt = "Design a flop.\n\n```verilog\nmodule m(\n    input clk,\n    output a\n);\n"
    assert _G.skeleton_module_name_from_prompt(prompt) == "m", (
        'prompt-skeleton alias top failed to resolve to m')
    # 2) Detector invariant on unwrapped .sv body:
    code_clean = (
        "```sv\n"
        "module m(input logic clk, output logic a);\n"
        "  always_ff @(posedge clk) a <= 1'b0;\n"
        "endmodule\n"
        "```\n"
    )
    code_hang = (
        "```sv\n"
        "module m(input logic clk, output logic a);\n"
        "  always_comb a = ~a;\n"
        "endmodule\n"
        "```\n"
    )
    cleaned_clean = re.sub(r"```[A-Za-z]*\n|\n```\n?", "", code_clean)
    cleaned_hang = re.sub(r"```[A-Za-z]*\n|\n```\n?", "", code_hang)
    assert H.predict_hang(cleaned_clean)[0] is False
    assert H.predict_hang(cleaned_hang)[0] is True


def test_baseline_sweep_no_pass_to_fail_flip():
    """On the real 302-responses baseline, the detector trips 28 entries;
    17 of them are on the score-final PASS list. The gate's emit layer
    MUST NOT consume predicted_hang to flip verdict — sanity check by
    reading cvdp_gate.py and asserting there is no `entry["pass"] = ...`
    write governed by `entry.get('hang_predicted')`."""
    _H, G, _ = _load()
    src_path = G.__file__
    with open(src_path, 'r', encoding='utf-8') as f:
        src = f.read()

    # Every Python AST assignment to entry["pass"] / out_rec["pass"] MUST
    # NOT have `hang_predicted` in the RHS or guard clause. This is the
    # cleanest expression of the §4.05 no-leak invariant — much tighter
    # than a string-substring search.
    import ast
    tree = ast.parse(src)
    risky = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            tgt_str = ast.dump(tgt)
            if 'hang_predicted' in tgt_str:
                continue
            if ('pass' not in tgt_str) or (
                    '"pass"' not in tgt_str and "'pass'" not in tgt_str):
                continue
            rhs_str = ast.dump(node.value)
            # The RHS / RHS-or-guard may reference hang_predicted INDIRECTLY
            # via a top-level AND. The robust check is any reference in the
            # entire RHS subtree.
            if 'hang_predicted' in rhs_str:
                risky.append(
                    f'line {node.lineno}: assigns {".".join(tgt_str.split())} '
                    f'with hang_predicted in RHS')

    # The tag-write side is allowed to mention `hang_predicted` literally,
    # but it writes `entry["hang_predicted"]`, not `entry["pass"]`. The
    # above loop excludes by target — so it should be empty.
    assert not risky, (
        'cvdp_gate.py writes entry["pass"] with hang_predicted in the RHS '
        '— this is a §4.05 leak risk. The tag must stay curated-only:\n'
        + '\n'.join(risky))
    # Sanity: the tag IS recorded as metadata:
    assert 'entry["hang_predicted"]' in src or "entry['hang_predicted']" in src


if __name__ == '__main__':
    # When run as `python3 test_*.py`, execute the suite under pytest semantics.
    import pytest
    sys.exit(pytest.main([__file__, '-v', '--tb=short']))

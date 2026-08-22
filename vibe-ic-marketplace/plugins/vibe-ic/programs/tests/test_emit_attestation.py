"""Tests for the GATE-AS-SOLE-EMIT-PATH enforcement: emit_attestation(.py) +
emit_attestation_check.py.

The load-bearing property: a sample EMITTED through the deterministic emit path (which calls
`record()`) verifies clean; a sample authored DIRECTLY into samples/ (no attestation) or
MUTATED after emit (sha256 drift) is detected as ungated, so a gate-bypassing run is flagged
NON-CANONICAL rather than scored as the runner's number.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import emit_attestation as ea  # noqa: E402
import emit_attestation_check as chk  # noqa: E402


def _samples(tmp_path):
    d = tmp_path / "samples"
    d.mkdir()
    return d


def _proj_with_ldocs(tmp_path):
    """A project root carrying Phase-1 generated_docs/L*.json so record() can stamp
    canonical provenance (the real emit callers always pass this)."""
    gd = tmp_path / "proj" / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    for n in ("L1", "L9"):
        (gd / f"{n}.json").write_text(f'{{"layer": "{n}"}}')
    return tmp_path / "proj"


def test_recorded_sample_verifies(tmp_path):
    d = _samples(tmp_path)
    s = d / "foo.v"; s.write_text("module foo; endmodule\n")
    ea.record(d, s, gates=["gates_atomic"], shape="C", phase1=_proj_with_ldocs(tmp_path))
    ok, ungated, total = ea.verify(d)
    assert ok is True and ungated == [] and total == 1


def test_recorded_sample_without_phase1_is_non_canonical(tmp_path):
    # No-back-compat contract: Phase-1 provenance is REQUIRED. A sample that passed
    # the emit gates but skipped Phase 1 is NON-canonical by default.
    d = _samples(tmp_path)
    s = d / "noprov.v"; s.write_text("module noprov; endmodule\n")
    ea.record(d, s, gates=["gates_atomic"], shape="C")  # no phase1
    ok, ungated, total = ea.verify(d)
    assert ok is False and ungated == ["noprov.v"] and total == 1


def test_directly_authored_sample_is_ungated(tmp_path):
    d = _samples(tmp_path)
    (d / "direct.sv").write_text("module direct; endmodule\n")  # no record() — bypassed the gate
    ok, ungated, total = ea.verify(d)
    assert ok is False and ungated == ["direct.sv"] and total == 1


def test_mutated_after_emit_is_ungated(tmp_path):
    d = _samples(tmp_path)
    s = d / "m.v"; s.write_text("module m; endmodule\n")
    ea.record(d, s, gates=["shape_b_guard_export"], shape="B")
    s.write_text("module m; wire tampered; endmodule\n")  # post-emit mutation → sha drift
    ok, ungated, _ = ea.verify(d)
    assert ok is False and ungated == ["m.v"]


def test_mixed_run_lists_only_the_ungated(tmp_path):
    d = _samples(tmp_path)
    g = d / "gated.v"; g.write_text("module gated; endmodule\n")
    ea.record(d, g, gates=["gates_atomic"], shape="C", phase1=_proj_with_ldocs(tmp_path))
    (d / "bypass.v").write_text("module bypass; endmodule\n")
    ok, ungated, total = ea.verify(d)
    assert ok is False and ungated == ["bypass.v"] and total == 2


def test_attestation_file_is_hidden_and_not_scoreable(tmp_path):
    # the attestation jsonl must be dot-hidden so the host scorer's *.sv/*.v glob ignores it
    d = _samples(tmp_path)
    s = d / "x.v"; s.write_text("module x; endmodule\n")
    ea.record(d, s, gates=["g"], shape="B")
    assert (d / ea.ATTEST_NAME).is_file() and ea.ATTEST_NAME.startswith(".")
    _ok, _ungated, total = ea.verify(d)
    assert total == 1  # only x.v counted, not the .emit_attestation.jsonl


# -------- the check CLI --------
def test_check_pass_on_fully_gated(tmp_path, capsys):
    d = _samples(tmp_path)
    s = d / "a.v"; s.write_text("module a; endmodule\n")
    ea.record(d, s, gates=["gates_atomic"], shape="C", phase1=_proj_with_ldocs(tmp_path))
    assert chk.main(["--samples", str(d)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_check_strict_fails_on_ungated(tmp_path, capsys):
    d = _samples(tmp_path)
    (d / "b.v").write_text("module b; endmodule\n")
    rc = chk.main(["--samples", str(d), "--strict"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "b.v" in out


def test_check_nonstrict_still_signals_but_labels_non_canonical(tmp_path, capsys):
    d = _samples(tmp_path)
    (d / "c.v").write_text("module c; endmodule\n")
    rc = chk.main(["--samples", str(d)])  # non-strict
    assert rc == 1
    assert "NON-CANONICAL" in capsys.readouterr().out


def test_check_skip_when_no_samples(tmp_path, capsys):
    d = _samples(tmp_path)
    assert chk.main(["--samples", str(d)]) == 0
    assert "SKIP" in capsys.readouterr().out


def test_check_missing_dir_is_arg_error(tmp_path):
    assert chk.main(["--samples", str(tmp_path / "nope")]) == 2

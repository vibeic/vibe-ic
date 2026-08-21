"""Tests for emit_attestation Phase-1 PROVENANCE — proof a scored sample's RTL
flowed through (doc|prompt) → Phase1(L*.json) → Phase2, not authored from the bare
prompt with Phase 1 skipped.

No-back-compat contract: Phase-1 provenance is REQUIRED for canonical by DEFAULT — a
sample whose attestation lacks `phase1.ran` is flagged ungated unless a caller explicitly
opts out with `require_phase1=False` (offline inspection of a pre-provenance run only).
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import emit_attestation as ea  # noqa: E402


def _mk_ldocs(gd: Path, names=("L1", "L9", "L13")):
    gd.mkdir(parents=True, exist_ok=True)
    for n in names:
        (gd / f"{n}.json").write_text(f'{{"layer": "{n}", "v": 1}}')


def test_provenance_from_project_root(tmp_path):
    proj = tmp_path / "proj"
    _mk_ldocs(proj / "phase1" / "generated_docs")
    p = ea.phase1_provenance(proj)
    assert p["ran"] is True
    assert p["ldoc_count"] == 3
    assert p["ldocs"] == ["L1", "L13", "L9"]
    assert len(p["digest"]) == 64


def test_provenance_from_generated_docs_dir(tmp_path):
    gd = tmp_path / "generated_docs"
    _mk_ldocs(gd)
    assert ea.phase1_provenance(gd)["ran"] is True


def test_provenance_absent_is_ran_false(tmp_path):
    assert ea.phase1_provenance(None) == {"ran": False}
    assert ea.phase1_provenance(tmp_path / "nope")["ran"] is False
    (tmp_path / "empty").mkdir()
    assert ea.phase1_provenance(tmp_path / "empty")["ran"] is False


def test_digest_changes_with_ldoc_content(tmp_path):
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    _mk_ldocs(gd)
    d1 = ea.phase1_provenance(proj)["digest"]
    (gd / "L9.json").write_text('{"layer": "L9", "v": 2}')  # mutate one L-doc
    d2 = ea.phase1_provenance(proj)["digest"]
    assert d1 != d2


def test_record_with_phase1_writes_key(tmp_path):
    proj = tmp_path / "proj"
    _mk_ldocs(proj / "phase1" / "generated_docs")
    samples = tmp_path / "samples"
    samples.mkdir()
    s = samples / "Prob_sample01.sv"
    s.write_text("module m; endmodule")
    ea.record(samples, s, gates=["g"], shape="C", phase1=proj)
    rec = ea._load(samples)[s.name]
    assert rec["phase1"]["ran"] is True and rec["phase1"]["ldoc_count"] == 3


def test_record_without_phase1_omits_key(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    s = samples / "Prob_sample01.sv"
    s.write_text("module m; endmodule")
    ea.record(samples, s, gates=["g"], shape="C")  # no phase1 arg
    assert "phase1" not in ea._load(samples)[s.name]


def test_verify_flags_missing_provenance_by_default(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    s = samples / "Prob_sample01.sv"
    s.write_text("module m; endmodule")
    ea.record(samples, s, gates=["g"], shape="C")  # no provenance
    # default ENFORCES Phase-1 provenance (no back-compat) → flagged NON-canonical
    ok, ungated, total = ea.verify(samples)
    assert not ok and ungated == [s.name] and total == 1
    # explicit opt-out only for offline inspection of a pre-provenance run
    ok2, ungated2, _ = ea.verify(samples, require_phase1=False)
    assert ok2 and ungated2 == []


def test_verify_passes_with_provenance(tmp_path):
    proj = tmp_path / "proj"
    _mk_ldocs(proj / "phase1" / "generated_docs")
    samples = tmp_path / "samples"
    samples.mkdir()
    s = samples / "Prob_sample01.sv"
    s.write_text("module m; endmodule")
    ea.record(samples, s, gates=["g"], shape="C", phase1=proj)
    ok, ungated, total = ea.verify(samples)  # default enforce
    assert ok and total == 1 and ungated == []

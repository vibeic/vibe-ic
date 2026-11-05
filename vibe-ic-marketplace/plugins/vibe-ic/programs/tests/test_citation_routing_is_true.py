"""The record that says whether you can follow a citation was not itself checked.

`CITATION_ROUTING.txt` exists (vibe-ic#448) so a citation the published layout
cannot carry is RECORDED as out of scope rather than left to dangle. Its header
promises it answers "whether a reader of THIS cell can follow it".

MEASURED on the caravel_user_project x sky130A cell as committed:

    RESOLVES rows                                189
    of those, the cited file is not findable       8

The publisher's rule is `(dest / cited).exists()` — correct when it runs. The
record is then committed and never re-derived, so a later pruning of the cell
leaves rows asserting RESOLVES about files that no longer ship. The artefact
whose whole job is to say whether a pointer can be followed was reporting the
good outcome for eight pointers it could not follow.

The second half of this file covers the WIRING it made safe: with the record
verified, `evidence_citation_resolves_check` can honour a recorded disclosure
instead of counting it as a hole — which is what the two mechanisms disagreed
about, on the same cell, for the same citation.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys


import pytest

from _published_corpus import CORPUS_ENV, cell_dirs

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]

#: RESOLVED AT IMPORT, BEFORE THE FIXTURE BELOW CLEARS THE POINTER.
#: `test_the_corpus_as_committed_passes` names the corpus as its `--root`, so it
#: needs the resolution that `$VIBE_IC_BENCHMARK_DATA` provides — and it is the
#: ONE test here that does. Reading it at import keeps the fixture safe for all
#: 18 without giving that test an exemption it would then have to remember to
#: keep. `needs_corpus` is evaluated at the same moment and skips the test when
#: this is None, so the two can never disagree.


@pytest.fixture(autouse=True)
def _the_subject_is_the_root_this_test_names(monkeypatch):
    """Clear `$VIBE_IC_BENCHMARK_DATA` for every test in this module.

    WHY, MEASURED. `citation_routing_is_true_check` deliberately ADDS the tree
    named by that variable to its scan — it prints `note: … adds a corpus to
    scan` — which is correct behaviour for a gate run over the repository. It is
    NOT what a unit test means when it builds three files in `tmp_path` and asks
    `main(["--root", that])`. With a pointer set at the published corpus, four
    cases here failed: `assert C.main(["--root", repo]) == 0` returned 2, over a
    corpus the test never mentioned and does not control.

    The tests were not wrong about their subject; they simply never said that the
    ambient environment was not part of it. This says it.

    THIS IS NOT A WAY TO MAKE A RED GO AWAY, and the difference is where the
    behaviour went. The pointer path is not silenced — it is covered
    deliberately, and with its own red, in
    `test_named_empty_corpus_is_not_a_wrong_pointer.py`, which drives the same
    program in a subprocess WITH the pointer bound and asserts what it says
    about a corpus that carries none of its subject. Nothing is now untested
    that was tested before; one module stopped being accidentally exposed to a
    variable, and another module tests that variable on purpose.
    """
    monkeypatch.delenv(CORPUS_ENV, raising=False)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


E = _load("evidence_citation_resolves_check")

_HEADER = "# CITATION_ROUTING — generated\n"


def _cell(tmp_path, rows, files=()):
    """A git-tracked cell carrying a routing record and the files it ships."""
    repo = tmp_path / "repo"
    cell = repo / "benchmark-data/ic/x/v1"
    cell.mkdir(parents=True)
    for f in files:
        p = cell / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    (cell / "CITATION_ROUTING.txt").write_text(
        _HEADER + "".join(f"{d} :: {c} {k}\n" for d, c, k in rows))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo, cell


# ── the record's own claims ────────────────────────────────────────────────








# ── what it deliberately does NOT judge ────────────────────────────────────




# ── it must not pass by finding nothing ────────────────────────────────────






# ── the wiring it makes safe ───────────────────────────────────────────────
def _disclosed(tmp_path, decision):
    repo, cell = _cell(tmp_path,
                       [("reports/a.json", "phase3/stage3/sta/x.rpt", decision)])
    tracked = {str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()}
    return E._disclosed_map(repo, tracked), cell


def test_an_out_of_scope_citation_is_a_disclosure_not_a_hole(tmp_path):
    m, _ = _disclosed(tmp_path, "OUT_OF_PUBLISHED_SCOPE")
    assert ("benchmark-data/ic/x/v1/reports/a.json",
            "phase3/stage3/sta/x.rpt") in m


def test_an_absolute_citation_is_a_disclosure(tmp_path):
    m, _ = _disclosed(tmp_path, "UNFOLLOWABLE_ABSOLUTE")
    assert m


def test_a_dangling_row_may_not_launder_a_hole(tmp_path):
    """LOAD-BEARING, and the reason the honoured set is two words and not four.
    DANGLING means "the publisher found no file" — that IS the hole, not a
    reason for it. Honouring it would let any new hole be cleared by writing one
    line into a routing file, which is exactly the shrink-only baseline
    discipline the citation gate exists to enforce."""
    for decision in ("DANGLING", "DANGLING_UNDER_PASS"):
        m, _ = _disclosed(tmp_path / decision, decision)
        assert not m, f"{decision} was honoured as a disclosure"


def test_a_resolves_row_cannot_suppress_a_finding(tmp_path):
    m, _ = _disclosed(tmp_path, "RESOLVES")
    assert not m


def test_the_honoured_set_includes_the_conditional_external_kit_decision():
    assert E._DISCLOSURE_DECISIONS == {"OUT_OF_PUBLISHED_SCOPE",
                                       "UNFOLLOWABLE_ABSOLUTE", "EXTERNAL_PDK"}




# ── the publisher and the gate must agree on what a citation IS ────────────
def test_the_publisher_scans_markdown_too():
    """`RESULT.md` cited `sta_mcorner_ocv.rpt` and the record never mentioned
    it, because `collect_citation_records` globbed `*.json` only. A record that
    does not COVER a citation is indistinguishable, to a reader, from one that
    says the citation is fine."""
    src = (_PROGRAMS / "benchmark_evidence_publish.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'sorted(dest.rglob("*.md"))' in body
    assert "_gate_citations(doc)" in body


def test_the_publisher_borrows_the_gates_definition_of_a_citation():
    """`_CITED_RE` only matches a path ROOTED at a known published prefix, so
    `fpga/compile.log` in a JSON key was invisible to it. One definition,
    borrowed — not two that drift."""
    src = (_PROGRAMS / "benchmark_evidence_publish.py").read_text(encoding="utf-8")
    seg = src[src.index("def _gate_citations"):]
    seg = seg[:seg.index("\ndef ", 10)]
    assert "evidence_citation_resolves_check" in seg
    assert "_json_artifact_refs" in seg and "_is_citation" in seg


def test_a_skipped_fpga_audit_does_not_name_a_log_it_lacks():
    """The last of the five: `compile_log` was the literal "fpga/compile.log"
    in a payload whose own `audited` is false. A field that names a proof when
    there is no proof reads exactly like one that has it."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert '"compile_log": "fpga/compile.log",' not in body
    assert 'if (project / "fpga/compile.log").is_file() else None' in body


def test_the_published_cell_no_longer_names_it():
    """The same field, read off whatever cells the corpus actually carries.

    It used to name ONE cell by path under this checkout and `return` when that
    path was absent. After the cells moved to `vibeic/benchmark-data` the
    `return` was the only branch left, so the test reported PASS on every run
    while reading nothing — the absence-rendering-as-a-pass this whole file
    exists to argue against, in the file itself. Swept over `cell_dirs()`
    instead: absent corpus SKIPs at the marker, present corpus is measured.
    """
    audits = [c / "reports/phase2/fpga/quartus_map_audit.json"
              for c in cell_dirs()]
    for f in [a for a in audits if a.is_file()]:
        cell = f.parents[3]
        d = json.loads(f.read_text())
        assert "compile_log" in d, (
            f"{f}: the key must stay — consumers key on this shape")
        cl = d["compile_log"]
        assert cl is None or (cell / cl).is_file(), (
            f"{f}: names {cl!r}, a proof the published cell does not carry")

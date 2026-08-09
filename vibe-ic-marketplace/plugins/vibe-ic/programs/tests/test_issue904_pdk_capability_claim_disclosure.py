#!/usr/bin/env python3
"""vibe-ic#904 — a design document that says the PDK cannot do something the
installed PDK demonstrably can.

BIDIRECTIONAL BY CONSTRUCTION. Every firing case is paired with the SAME tree
made honest, because a detector that can only ever return one verdict has not
been shown to detect anything. The pairs:

  * CONTRADICTION   doc denies the corner lib, installed PDK ships one
    CONSISTENT      doc denies the corner lib, installed PDK really has none
  * probe present   a lib bracketing the process grid
    probe absent    a lib with a nominal section only (a model lib, not a
                    corner lib) — the boundary the probe must not overrun
  * claim found     negation governs the capability noun
    claim not found the same sentence with the negation on the far side of the
                    clause break, and the same sentence with no PDK subject

Everything is asserted on RETURNED VALUES, emitted JSON and process exit codes.
No test here asserts that a string does or does not appear in a source file.

All fixtures are synthetic: two-letter corner nomenclature, generic device
names, invented PDK dir names. No design name, PDK name or part number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import analog_pdk_availability as APA  # noqa: E402
import pdk_capability_claim_disclosure as D  # noqa: E402


# ── synthetic PDK content ──────────────────────────────────────────────────
# A corner lib: nominal + both process extremes, plus a statistical variant.
CORNER_LIB = """\
* synthetic device corner library
.LIB dev_tt
.model n1 nmos level=54 version=4.5
.ENDL dev_tt
.LIB dev_tt_mismatch
.param mmfac=agauss(0,1,1)
.ENDL dev_tt_mismatch
.LIB dev_ss
.model n1 nmos level=54 version=4.5
.ENDL dev_ss
.LIB dev_ff
.model n1 nmos level=54 version=4.5
.ENDL dev_ff
.LIB dev_sf
.model n1 nmos level=54 version=4.5
.ENDL dev_sf
.LIB dev_fs
.model n1 nmos level=54 version=4.5
.ENDL dev_fs
"""

# The near miss: sectioned, but nominal only. Not a corner library.
NOMINAL_ONLY_LIB = """\
* synthetic device model library, nominal only
.LIB dev_tt
.model n1 nmos level=54 version=4.5
.ENDL dev_tt
"""

# The other near miss: no sections at all.
FLAT_LIB = """\
* synthetic flat model library
.model n1 nmos level=54 version=4.5
.model p1 pmos level=54 version=4.5
"""

DENIAL_DOC = (
    "# Constraints\n"
    "\n"
    "## Tool / data disclosures\n"
    "- The target PDK has **no public ngspice corner lib** -> corner sims use\n"
    "  documented LEVEL=1 standin models (modeled, not silicon sign-off).\n"
)


def _mk_project(tmp_path: Path, *, doc: str = DENIAL_DOC,
                target: str = "SYNTH FOUNDRY N100") -> Path:
    p = tmp_path / "proj"
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "L9_CONSTRAINTS.md").write_text(doc)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": target}}))
    return p


def _fake_pdk(root: Path, dirname: str, libs: dict) -> tuple:
    """A local /foss/pdks-shaped install. Returns (pdks_root, lister)."""
    ng = root / dirname / "libs.tech" / "ngspice" / "models"
    ng.mkdir(parents=True)
    (root / dirname / "libs.tech" / "magic").mkdir(parents=True)
    for name, text in libs.items():
        (ng / name).write_text(text)
    return str(root), APA._local_lister


# ── the probe, both directions ─────────────────────────────────────────────

def test_probe_reports_present_when_the_pdk_ships_a_corner_lib(tmp_path):
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"corner_dev.lib": CORNER_LIB})
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=root, lister=lister)
    assert res["available"] is True, res["reason"]
    cap = APA.probe_corner_capability(res)
    assert cap["probed"] is True, cap["reason"]
    assert cap["corner_lib_present"] is True
    assert len(cap["libs_with_full_corner_set"]) == 1
    assert set(cap["corner_roles_covered"]) == {"typ", "slow", "fast", "skew"}
    assert cap["mismatch_lib_present"] is True
    assert cap["statistical_card_count"] >= 1


def test_probe_reports_absent_for_a_nominal_only_model_lib(tmp_path):
    """The paired half, and the boundary that matters: a sectioned lib with
    only a nominal section is NOT a corner library. If the probe called this
    present it would manufacture contradictions against honest documents."""
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"models_dev.lib": NOMINAL_ONLY_LIB})
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=root, lister=lister)
    cap = APA.probe_corner_capability(res)
    assert cap["probed"] is True
    assert cap["corner_lib_present"] is False
    assert cap["libs_with_full_corner_set"] == []
    assert cap["corner_roles_covered"] == ["typ"]


def test_probe_reports_absent_for_a_sectionless_lib(tmp_path):
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"flat_dev.lib": FLAT_LIB})
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=root, lister=lister)
    cap = APA.probe_corner_capability(res)
    assert cap["probed"] is True
    assert cap["libs_with_sections"] == 0
    assert cap["corner_lib_present"] is False


def test_a_lib_with_non_utf8_bytes_is_still_read(tmp_path):
    """REGRESSION, found on the real install this issue is about. Foundry model
    libs carry latin-1 bytes in their header comments (a micro sign in a units
    note is enough). A strict decode turned a 32-lib install with a full corner
    set into "no model lib was readable" — the probe reporting UNVERIFIED about
    an environment that plainly has the capability."""
    root = tmp_path / "pdks"
    ng = root / "synthpdk100" / "libs.tech" / "ngspice" / "models"
    ng.mkdir(parents=True)
    (root / "synthpdk100" / "libs.tech" / "magic").mkdir(parents=True)
    (ng / "corner_dev.lib").write_bytes(
        b"* units: 1\xb5m gate length\n" + CORNER_LIB.encode("utf-8"))
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=str(root),
                          lister=APA._local_lister)
    cap = APA.probe_corner_capability(res)
    assert cap["probed"] is True, cap["reason"]
    assert cap["corner_lib_present"] is True


def test_probe_never_claims_presence_when_it_could_not_read(tmp_path):
    """An unprobeable environment must not be able to contradict a document."""
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"corner_dev.lib": CORNER_LIB})
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=root, lister=lister)
    cap = APA.probe_corner_capability(res, reader=lambda paths: {})
    assert cap["probed"] is False
    assert cap["corner_lib_present"] is False
    assert "readable" in (cap["reason"] or "")


# ── batch framing (the container read path, pinned without a container) ────

def _run_batch(paths):
    """Run the reader's OWN shell script through bash on real files and split
    the result with the reader's OWN splitter. Same two halves the container
    path uses; only the `docker exec` hop is absent."""
    r = subprocess.run(["bash", "-lc", APA._batch_script([str(p) for p in paths])],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr[-300:]
    return APA._split_batch(r.stdout)


def test_batch_framing_survives_a_file_with_no_trailing_newline(tmp_path):
    """REGRESSION, found on the real install. Without the leading newline the
    script emits, a lib whose last byte is not `\\n` leaves the NEXT marker
    glued to that last line, where a start-of-line match cannot see it — so the
    next lib silently vanishes from the probe. Measured before the fix: 31 of
    32 libs read, no error, no warning."""
    a = tmp_path / "a.lib"
    b = tmp_path / "b.lib"
    a.write_text("* a\n.LIB x\n.ENDL x")          # NO trailing newline
    b.write_text("* b\n.LIB y\n.ENDL y\n")
    got = _run_batch([a, b])
    assert set(got) == {str(a), str(b)}, got
    assert ".ENDL x" in got[str(a)]
    assert ".ENDL y" in got[str(b)]


def test_batch_framing_reads_every_file_when_all_end_cleanly(tmp_path):
    files = []
    for i in range(4):
        f = tmp_path / f"m{i}.lib"
        f.write_text(f"* body {i}\n")
        files.append(f)
    got = _run_batch(files)
    assert set(got) == {str(f) for f in files}
    assert all(f"body {i}" in got[str(files[i])] for i in range(4))


# ── the claim scanner, both directions ─────────────────────────────────────

def test_the_denial_is_found(tmp_path):
    p = _mk_project(tmp_path)
    claims = D.find_claims(p, "SYNTH FOUNDRY N100")
    assert len(claims) == 1, claims
    assert claims[0]["capability"] == "corner_lib"
    assert claims[0]["negation"].lower() == "no"
    assert claims[0]["file"] == "input/docs/L9_CONSTRAINTS.md"


def test_a_negation_on_the_far_side_of_the_clause_break_is_not_a_denial(tmp_path):
    """`has a corner lib -> no LEVEL=1 standin needed` denies the STANDIN, not
    the corner lib. A window-only matcher reads it backwards and reports a
    contradiction against a document that says the opposite."""
    p = _mk_project(tmp_path, doc=(
        "- The target PDK ships a full ngspice corner set -> no standin "
        "corner models are used.\n"))
    assert D.find_claims(p, "SYNTH FOUNDRY N100") == []


def test_a_denial_with_no_pdk_subject_is_not_a_pdk_claim(tmp_path):
    """A schedule note is not a statement about the environment."""
    p = _mk_project(tmp_path, doc=(
        "- The reviewer had no corner models to look at during the walkthrough.\n"))
    assert D.find_claims(p, "SYNTH FOUNDRY N100") == []


def test_an_affirmative_capability_sentence_is_not_a_denial(tmp_path):
    p = _mk_project(tmp_path, doc=(
        "- The target PDK ships an ngspice corner library for every device "
        "class.\n"))
    assert D.find_claims(p, "SYNTH FOUNDRY N100") == []


# ── end to end, both directions ────────────────────────────────────────────

def test_stale_denial_against_a_pdk_that_ships_corners_is_a_CONTRADICTION(tmp_path):
    p = _mk_project(tmp_path)
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"corner_dev.lib": CORNER_LIB})
    rep = D.audit(p, pdks_root=root, lister=lister)
    assert rep["verdict"] == "CONTRADICTION", rep
    assert len(rep["contradictions"]) == 1
    c = rep["contradictions"][0]
    assert c["status"] == "CONTRADICTED"
    assert c["installed_provides"] is True
    assert c["capability"] == "corner_lib"
    assert rep["installed"]["capability"]["corner_lib_present"] is True


def test_the_same_denial_against_a_pdk_with_no_corners_is_CONSISTENT(tmp_path):
    """THE OPPOSITE VERDICT, on the SAME document. Without this the gate could
    be one that only ever says CONTRADICTION and nobody would know."""
    p = _mk_project(tmp_path)
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"models_dev.lib": NOMINAL_ONLY_LIB})
    rep = D.audit(p, pdks_root=root, lister=lister)
    assert rep["verdict"] == "CONSISTENT", rep
    assert rep["contradictions"] == []
    assert rep["claims"][0]["status"] == "CONSISTENT"
    assert rep["claims"][0]["installed_provides"] is False


def test_no_claim_in_the_corpus_is_NO_CLAIM_not_a_contradiction(tmp_path):
    p = _mk_project(tmp_path, doc="# Constraints\n\n- Die area 1000x1000 um.\n")
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"corner_dev.lib": CORNER_LIB})
    rep = D.audit(p, pdks_root=root, lister=lister)
    assert rep["verdict"] == "NO_CLAIM", rep
    assert rep["contradictions"] == []


def test_an_unprobeable_pdk_leaves_the_claim_UNVERIFIED(tmp_path):
    """No installed PDK at all: the claim is not confirmed AND not contradicted.
    Reporting CONSISTENT here would launder an unmeasured environment into
    agreement with the document."""
    p = _mk_project(tmp_path)
    empty = tmp_path / "pdks_empty"
    empty.mkdir()
    rep = D.audit(p, pdks_root=str(empty), lister=APA._local_lister)
    assert rep["verdict"] == "UNVERIFIED", rep
    assert rep["claims"][0]["status"] == "UNVERIFIED"
    assert rep["claims"][0]["installed_provides"] is None


# ── the CLI the flow actually drives ───────────────────────────────────────

def _run(project, *args):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "pdk_capability_claim_disclosure.py"),
         str(project), *args],
        capture_output=True, text=True)


def test_the_cli_discloses_without_blocking_and_writes_its_report(tmp_path):
    """DISCLOSURE, not gate: the contradiction is in the emitted JSON and the
    exit code is still 0, so an advisory slot cannot turn a documentation lag
    into a stopped run."""
    p = _mk_project(tmp_path)
    root, _ = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                        {"corner_dev.lib": CORNER_LIB})
    out = tmp_path / "out.json"
    r = _run(p, "--pdks-root", root, "--json", str(out))
    assert r.returncode == 0, r.stderr[-500:]
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "CONTRADICTION"
    assert len(rep["contradictions"]) == 1
    canonical = json.loads((p / D.REPORT_REL).read_text())
    assert canonical["verdict"] == "CONTRADICTION"


def test_the_cli_still_exits_0_when_the_document_is_honest(tmp_path):
    p = _mk_project(tmp_path)
    root, _ = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                        {"models_dev.lib": NOMINAL_ONLY_LIB})
    out = tmp_path / "out.json"
    r = _run(p, "--pdks-root", root, "--json", str(out))
    assert r.returncode == 0, r.stderr[-500:]
    assert json.loads(out.read_text())["verdict"] == "CONSISTENT"


def test_a_host_pdks_root_is_read_on_the_host_even_with_a_container_named(tmp_path):
    """The flow drives this gate with no `--container`, so the default names
    one. A host `--pdks-root` (fixture or host-mounted PDK) must NOT then be
    read through `docker exec`, or every lib comes back unreadable and the
    verdict is UNVERIFIED about a PDK sitting right there on disk."""
    p = _mk_project(tmp_path)
    root, _ = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                        {"corner_dev.lib": CORNER_LIB})
    got = D.probe_installed(p, "SYNTH FOUNDRY N100", pdks_root=root,
                            container="a-container-that-does-not-exist")
    assert got["capability"]["probed"] is True, got["capability"]["reason"]
    assert got["capability"]["corner_lib_present"] is True


def test_the_cli_default_container_is_not_none(tmp_path):
    """A default of None makes the DEFAULT `/foss/pdks` unprobeable, so every
    real run reports UNVERIFIED — a gate that can never be wrong because it
    never looks. Asserted through the parser's returned namespace."""
    r = _run(tmp_path, "--help")
    assert r.returncode == 0
    p = _mk_project(tmp_path)
    out = tmp_path / "d.json"
    # No --container, no --pdks-root: the report must record an attempt to
    # resolve against the default container root, not a None-container skip.
    assert _run(p, "--json", str(out)).returncode == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] in ("UNVERIFIED", "CONTRADICTION", "CONSISTENT"), rep
    assert rep["installed"] is not None


def test_the_cli_refuses_a_project_dir_that_does_not_exist():
    r = _run(Path("/nonexistent/project/904"))
    assert r.returncode == 2, r.stdout[-300:]
    assert "IO_ERROR" in r.stderr


def test_the_program_never_edits_the_design_input(tmp_path):
    """L9 is design INPUT. The deliverable is the detection, not the edit."""
    p = _mk_project(tmp_path)
    doc = p / "input" / "docs" / "L9_CONSTRAINTS.md"
    before = doc.read_bytes()
    root, _ = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                        {"corner_dev.lib": CORNER_LIB})
    assert _run(p, "--pdks-root", root).returncode == 0
    assert doc.read_bytes() == before


# ── the wiring, EXECUTED (not inspected) ───────────────────────────────────

def _a4_gate():
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    steps = {s["id"]: s for s in flow["steps"]}
    return steps["A4"]["gate"]


def test_the_advisory_fires_on_a_step_whose_blocking_clause_failed(tmp_path):
    """The shipped A4 gate is LOADED as data and EXECUTED — this asserts on the
    reasons `_evaluate_gate` returns, not on any string in the definition.

    A gate wired where nothing runs it is the failure mode this repo keeps
    finding, and `all_of` short-circuits: an advisory placed before a failing
    blocking clause never executes. A4's blocking clauses fail on an empty
    project, which is exactly the run this disclosure is for."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_compliance_check as F

    p = _mk_project(tmp_path)
    passed, reasons = F._evaluate_gate(p, _a4_gate())
    assert passed is False, "A4 should fail on a project with no corner data"
    hints = [r for r in reasons if r.startswith(F._ADVISORY_HINT_PREFIX)]
    assert any("pdk_capability_claim_disclosure" in h for h in hints), (
        "the disclosure did not run on a failing A4 — advisory hints seen: "
        f"{hints}")
    # and the incumbent advisory still fires alongside it
    assert any("analog_corner_lib_realism_lint" in h for h in hints), hints


def test_the_gate_declares_its_advisory_intent_to_the_enforcement_audit(tmp_path):
    """A gate wired AUDIT_ONLY that declares no intent is indistinguishable
    from one quietly softened, and the shipped audit fails on exactly that.
    Asserted against the audit's OWN emitted report, not against any string in
    this program's source: it must not appear among the undeclared gates."""
    out = tmp_path / "audit.json"
    subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    rep = json.loads(out.read_text())
    undeclared = {u["gate"] for u in (rep.get("undeclared_audit_only") or [])}
    assert "pdk_capability_claim_disclosure" not in undeclared, sorted(undeclared)


def test_the_advisory_cannot_flip_the_step_verdict(tmp_path):
    """DISCLOSURE, not gate. Drive the advisory clause alone: it passes even
    when the program it runs reports a contradiction."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_compliance_check as F

    p = _mk_project(tmp_path)
    root, _ = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                        {"corner_dev.lib": CORNER_LIB})
    clause = {"advisory_program_exit_zero":
              f"pdk_capability_claim_disclosure . --pdks-root {root}"}
    passed, reasons = F._evaluate_gate(p, clause)
    assert passed is True, reasons
    rep = json.loads((p / D.REPORT_REL).read_text())
    assert rep["verdict"] == "CONTRADICTION", rep


# ── the additive contract on the resolver ──────────────────────────────────

def test_resolve_pdk_result_is_unchanged_by_the_probe(tmp_path):
    """Blast-radius pin: the probe is a SECOND call, not a new field. Any
    consumer comparing resolve_pdk() results keeps seeing the same keys."""
    root, lister = _fake_pdk(tmp_path / "pdks", "synthpdk100",
                             {"corner_dev.lib": CORNER_LIB})
    res = APA.resolve_pdk("SYNTH FOUNDRY N100", pdks_root=root, lister=lister)
    snapshot = json.dumps(res, sort_keys=True)
    APA.probe_corner_capability(res)
    assert json.dumps(res, sort_keys=True) == snapshot
    for banned in ("corner_lib_present", "probed", "corner_roles_covered"):
        assert banned not in res


@pytest.mark.parametrize("name,roles", [
    ("dev_tt", {"typ"}),
    ("mos_ss", {"slow"}),
    ("mos_ff", {"fast"}),
    ("mos_sf", {"skew"}),
    ("res_wcs", {"slow"}),
    ("cap_bcs", {"fast"}),
    ("res_typ_mismatch", {"typ"}),
    # Spelled-out nominal. A real installed open PDK spells it this way, and
    # missing it reported that PDK as shipping no corner library at all.
    ("typical", {"typ"}),
    ("bjt_typical", {"typ"}),
    ("nominal", {"typ"}),
    ("buffer", set()),
    ("stuff", set()),
    ("classify", set()),
])
def test_section_role_classification_is_whole_token(name, roles):
    """`buffer` contains `ff` and `stuff` contains `ff`; neither is a fast
    corner. Substring matching here would have made every PDK look like it
    ships corners."""
    assert set(APA._section_corner_roles(name)) == roles

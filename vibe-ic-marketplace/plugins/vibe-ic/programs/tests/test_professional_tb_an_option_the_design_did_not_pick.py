"""Step 4 — `professional_tb_check` does not demand an L10 case the DESIGN
declared it does not have, and says so by name.

MEASURED on subservient x gf180mcuD (run2, main 240c0a353): 7 of 10 declared
L10 cases carry a `sim_executed=true` PASS row; the other three are the
`(若 Plugin 選 M / Zicsr / C)` rows, whose L10 entries carry
`applies_when: {option: ...}` while `plugin_output/declaration.json` records
`isa_extensions: ["I", "Zifencei"]`. Step 4's sibling gate
`cpu_functional_oracle_waiver_check` already narrows ITS denominator on that
declared basis (R-0915-102); this gate did not, so the step judged two
populations and sat at `partial_population` on three oracles no
RV32I-Zifencei build can execute.

The narrowing is the SIBLING'S OWN helper, fail-closed both ways, and every
narrowed case is disclosed — never dropped, never a pass.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_check as P  # noqa: E402
import _path_layout as _pl  # noqa: E402
import _l10_execution as _l10x  # noqa: E402

M_ROW = {"name": "mul_div", "applies_when": {
    "option": "M", "stated": "(若 Plugin 選 M)", "source": "L7 table"}}


def _junit(ids):
    cases = "".join(f'  <testcase classname="l10_unit_tb" name="{i}" '
                    f'time="1.0"></testcase>\n' for i in ids)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n'
            f'<testsuite name="l10_unit_tb" tests="{len(ids)}" failures="0" '
            f'errors="0" skipped="0">\n{cases}</testsuite>\n</testsuites>\n')


def _project(tmp_path, rows, declaration):
    p = tmp_path / "proj"
    ids = [r["name"] for r in rows]
    junit = p / P._L10_UNIT_JUNIT_REL
    junit.parent.mkdir(parents=True)
    junit.write_text(_junit(ids))
    docs = _pl.generated_docs_dir(p)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": rows}))
    rec = p / "reports" / "phase2" / "sim"
    rec.mkdir(parents=True)
    (rec / "l10_execution.json").write_text(json.dumps(
        {"source_junit": P._L10_UNIT_JUNIT_REL.as_posix()}))
    if declaration is not None:
        (p / "plugin_output").mkdir()
        (p / "plugin_output" / "declaration.json").write_text(
            json.dumps(declaration))
    return p, ids


def _wire(monkeypatch, project, ids, states):
    record = {"available": True, "malformed": [],
              "rows": {i: {} for i in ids},
              "path": str(project / "reports/phase2/sim/l10_execution.json")}
    monkeypatch.setattr(_l10x, "load_record", lambda *a, **k: record)
    monkeypatch.setattr(_l10x, "case_state", lambda cid, rec: states[cid])


PASS = (_l10x.PASS, "execution record row (verdict=PASS)")
UNRUN = (_l10x.NOT_EXECUTED, "simulator ran the substance-floor scaffold, but "
         "the declared L10 case oracle was not executed")
RV = {"isa_extensions": ["I", "Zifencei"]}


def _run(tmp_path, monkeypatch, rows, declaration, states):
    proj, ids = _project(tmp_path, rows, declaration)
    _wire(monkeypatch, proj, ids, states)
    return P.l10_unit_tb_track(proj)


def test_an_unselected_option_is_not_demanded_and_is_disclosed(tmp_path, monkeypatch):
    """RED ON MAIN (NOT_CHECKED naming mul_div). The measured shape."""
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, M_ROW], RV,
               {"rv32i": PASS, "mul_div": UNRUN})
    assert out["verdict"] == "PASS", out
    na = out["design_declared_na"]
    assert na["decided"] is True and na["design_selected"] == ["i", "zifencei"]
    assert [(c["case"], c["option"], c["record_state"]) for c in na["cases"]] \
        == [("mul_div", "M", _l10x.NOT_EXECUTED)]
    assert out["l10_cases"] == 1 and out["declared_case_count"] == 2
    assert "nothing about it is claimed verified" in na["note"]


def test_an_option_the_design_did_select_is_still_demanded(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, M_ROW],
               {"isa_extensions": ["I", "M"]},
               {"rv32i": PASS, "mul_div": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out
    assert [r["case"] for r in out["cases_not_executed"]] == ["mul_div"]
    assert out["design_declared_na"]["cases"] == []


def test_no_declaration_decides_nothing(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, M_ROW], None,
               {"rv32i": PASS, "mul_div": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out
    assert out["design_declared_na"]["decided"] is False
    assert [r["case"] for r in out["cases_not_executed"]] == ["mul_div"]


def test_a_declaration_with_no_selection_field_decides_nothing(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, M_ROW],
               {"top_module": "x"}, {"rv32i": PASS, "mul_div": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out


def test_a_row_without_applies_when_is_still_demanded(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, {"name": "plain"}],
               RV, {"rv32i": PASS, "plain": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out
    assert [r["case"] for r in out["cases_not_executed"]] == ["plain"]


def test_a_failure_in_a_narrowed_case_is_still_a_FAIL(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, M_ROW], RV,
               {"rv32i": PASS, "mul_div": (_l10x.FAIL, "assertion fired")})
    assert out["verdict"] == "FAIL", out


def test_all_cases_narrowed_is_not_a_pass(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, [M_ROW], RV, {"mul_div": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out
    assert "nothing was verified" in out["reason"]


def test_one_narrowing_the_siblings_own_helper():
    """The two step-4 gates must judge ONE population: this gate calls the
    sibling's public helpers and carries no applies_when reader of its own."""
    src = (PROG / "professional_tb_check.py").read_text()
    assert "_w.split_design_declared_na(" in src
    assert "_w.design_selected_options(" in src
    assert "def design_selected_options" not in src
    assert "def split_design_declared_na" not in src


# --- review w3u4f4z66 -------------------------------------------------------
import pytest  # noqa: E402


def _row(name, option):
    return {"name": name, "applies_when": {"option": option,
                                           "stated": f"(若 Plugin 選 {option})",
                                           "source": "L7 table"}}


@pytest.mark.parametrize("option,declared", [
    ("Zmmul", ["I", "M"]),          # a SUBSET of M: declaring M does not make it absent
    ("M", ["I", "Zmmul"]),          # ...and declaring Zmmul does not make M absent
    ("RV32M", ["I", "Zifencei"]),
    ("M (optional)", ["I", "Zifencei"]),
    ("M", ["RV32IMC"]),
    ("M", ["G"]),
])
def test_an_unrecognised_spelling_never_narrows(tmp_path, monkeypatch,
                                                option, declared):
    """#3: fail closed -- narrow only when the option AND every declared entry
    are in the closed vocabulary; otherwise the case is DEMANDED, with why."""
    out = _run(tmp_path, monkeypatch, [{"name": "rv32i"}, _row("x", option)],
               {"isa_extensions": declared},
               {"rv32i": PASS, "x": UNRUN})
    assert out["verdict"] == "NOT_CHECKED", out
    assert [r["case"] for r in out["cases_not_executed"]] == ["x"]
    dna = out["design_declared_na"]
    assert dna["cases"] == []
    assert [r["case"] for r in dna["not_narrowed"]] == ["x"]
    assert "DEMANDED" in dna["not_narrowed"][0]["why"]


def _sidecar(project, verified):
    (project / "plugin_output" / "declaration.provenance.json").write_text(
        json.dumps({"fields": {"isa_extensions": {
            "provenance": "author_declared" if verified else "unknown",
            "provenance_verified": verified}}}))


def test_an_unverified_basis_is_disclosed_as_unverified(tmp_path, monkeypatch):
    """#2: the narrowing still follows the sibling's policy, but a reader sees
    that the declaration's selection is not verified."""
    proj, ids = _project(tmp_path, [{"name": "rv32i"}, M_ROW], RV)
    _sidecar(proj, False)
    _wire(monkeypatch, proj, ids, {"rv32i": PASS, "mul_div": UNRUN})
    basis = P.l10_unit_tb_track(proj)["design_declared_na"]["basis"]
    assert basis["field"] == "isa_extensions"
    assert basis["provenance_verified"] is False
    assert "UNVERIFIED" in basis["why"]


def test_a_verified_basis_says_so_and_a_missing_sidecar_is_unverified(
        tmp_path, monkeypatch):
    proj, ids = _project(tmp_path, [{"name": "rv32i"}, M_ROW], RV)
    _wire(monkeypatch, proj, ids, {"rv32i": PASS, "mul_div": UNRUN})
    assert "no readable provenance sidecar" in \
        P.l10_unit_tb_track(proj)["design_declared_na"]["basis"]["why"]
    _sidecar(proj, True)
    basis = P.l10_unit_tb_track(proj)["design_declared_na"]["basis"]
    assert basis["provenance_verified"] is True and "why" not in basis

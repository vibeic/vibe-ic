"""vibe-ic#1330 — an output declared before the verdict that may destroy it.

`_emit_multi_corner_sta` unlinks its per-corner report when OpenSTA black-boxed a
master (#437(c): rc==0 plus a written report is not evidence anything was timed).
The call site declared `rpt` via `_docker_exec(outputs=[rpt])`, so the ledger
recorded a digest for a file removed three statements later.

Both rules hold once the declaration moves to the surviving path, and these tests
pin BOTH halves — the helper's refusal, and the AST rule that must still fire if
anyone re-declares up front.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path


def _runner_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "programs" / "phase3_one_shot_runner.py"
        if cand.is_file():
            return cand
    raise AssertionError("phase3_one_shot_runner.py not found above this test")


_RUNNER = _runner_path()


def _load():
    spec = importlib.util.spec_from_file_location("p3run", _RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p3run"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── the helper's refusal ──────────────────────────────────────────────────
def test_a_destroyed_artefact_records_NOTHING(tmp_path, monkeypatch):
    """The whole point: no row for a file that did not survive."""
    m = _load()
    monkeypatch.setattr(m, "_PROV_SINK", str(tmp_path), raising=False)
    gone = tmp_path / "sta_ss.rpt"          # never created
    m._log_surviving_artefact([gone], produced_by="_emit_multi_corner_sta")
    sink = tmp_path / "provenance.jsonl"
    assert not sink.exists() or sink.read_text() == "", (
        "an unlinked report must leave no artefact row; a digest for a file that "
        "does not exist is the unauditable record #1330 is about")


def test_a_surviving_artefact_IS_recorded(tmp_path, monkeypatch):
    """The opposite direction — the fix must not silence the honest case."""
    m = _load()
    monkeypatch.setattr(m, "_PROV_SINK", str(tmp_path), raising=False)
    kept = tmp_path / "sta_tt.rpt"
    kept.write_text("wns -33.88\n")
    m._log_surviving_artefact([kept], produced_by="_emit_multi_corner_sta")
    rows = [json.loads(l) for l in
            (tmp_path / "provenance.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1, rows
    assert rows[0]["record"] == "artefact"
    assert rows[0]["produced_by"] == "_emit_multi_corner_sta"
    assert rows[0]["outputs"], "a surviving artefact must carry its digest"


def test_the_record_kind_is_NOT_invocation(tmp_path, monkeypatch):
    """Two `invocation` rows for one tool run would be a worse misstatement."""
    m = _load()
    monkeypatch.setattr(m, "_PROV_SINK", str(tmp_path), raising=False)
    kept = tmp_path / "r.rpt"
    kept.write_text("x")
    m._log_surviving_artefact([kept], produced_by="fn")
    row = json.loads((tmp_path / "provenance.jsonl").read_text().splitlines()[0])
    assert row["record"] != "invocation"


# ── the structural rule, so a re-declaration cannot come back quietly ─────
def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(_RUNNER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def test_the_unlinking_call_site_declares_no_outputs_up_front():
    """`outputs=` at this call site is what made the digest unauditable."""
    fn = _fn("_emit_multi_corner_sta")
    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if callee != "_docker_exec":
            continue
        for kw in node.keywords:
            if kw.arg == "outputs":
                offenders.append(node.lineno)
    assert not offenders, (
        f"_docker_exec(outputs=...) is back at line(s) {offenders} in a function "
        f"that unlinks its own report — declare on the surviving path instead "
        f"(_log_surviving_artefact)")


def test_the_surviving_path_still_declares_something():
    """The mirror image: moving the declaration must not DROP it."""
    fn = _fn("_emit_multi_corner_sta")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and (getattr(n.func, "id", None) == "_log_surviving_artefact")]
    assert calls, ("nothing declares the corner report any more — the fix must "
                   "move the declaration, not delete it")


def test_the_unlink_is_still_there():
    """#437(c) must survive this fix: a black-boxed corner leaves NO report."""
    fn = _fn("_emit_multi_corner_sta")
    # The NAME matters. This function also unlinks `debris` (unrelated
    # cleanup), so asserting "some unlink exists" passes with the #437(c) one
    # deleted — measured: removing `rpt.unlink()` left this test green until it
    # was pinned to the receiver.
    unlinked = {getattr(n.func.value, "id", None)
                for n in ast.walk(fn) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "unlink"}
    assert "rpt" in unlinked, (
        f"the #437(c) `rpt.unlink()` is gone (unlinked receivers: "
        f"{sorted(x for x in unlinked if x)}) — a black-boxed corner would ship "
        f"a falsely-clean 0.00 report again")

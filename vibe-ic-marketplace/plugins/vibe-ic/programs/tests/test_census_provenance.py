#!/usr/bin/env python3
"""`_census_provenance` — the three states, and that NOT_MEASURED is earned.

WHAT THIS FILE LOCKS
====================
1. The provenance a GENERATED block declares is READ, not assumed. A block with
   no `Corpus at generation:` line is NOT_MEASURED, never a comparison made on
   the strength of a default nobody wrote down.
2. When the declared provenance CAN be arranged, it is arranged and a real
   verdict is reached. NOT_MEASURED is the answer to "I could not", never to "it
   would have been easier".
3. When it cannot, the refusal NAMES what could not be arranged — which corpus,
   which commit, which direction.
4. The environment is restored on every path, because the module that removes an
   invisible environment pointer must not leave one behind.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/test_census_provenance.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _census_provenance as PROV  # noqa: E402
import _published_corpus as PC  # noqa: E402

_REPO = Path(__file__).resolve().parents[5]


def _block(line: str) -> str:
    """A minimal generated block carrying one provenance line."""
    return ("<!-- BEGIN GENERATED CENSUS -->\n"
            "**621 cells: 541 ENFORCED.**\n\n"
            f"{line}\n\n"
            "<!-- END GENERATED CENSUS -->\n")


def _corpus(root: Path, *, cells: bool = True, commit: bool = True) -> Path:
    """A tree that IDENTIFIES ITSELF as the published corpus, per `_published_corpus`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / PC.CORPUS_CONTRACT).write_text("publishing contract\n")
    (root / "ic").mkdir(exist_ok=True)
    if cells:
        (root / "ic" / "design" / "v1_open_pdk").mkdir(parents=True, exist_ok=True)
        (root / "ic" / "design" / "v1_open_pdk" / "cell.json").write_text("{}\n")
    if commit:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "corpus"],
                       check=True)
    return root


@pytest.fixture(autouse=True)
def _cold(monkeypatch):
    """Every case starts with no recorded derivation, as a fresh process would."""
    monkeypatch.setattr(PROV, "_DERIVED_UNDER", None)
    monkeypatch.delenv(PC.CORPUS_ENV, raising=False)


# --------------------------------------------------------------------------
# what the block says
# --------------------------------------------------------------------------
def test_the_declared_state_is_read_from_the_block():
    d = PROV.declared_provenance(_block(
        "Corpus at generation: NOT_OFFERED — no published cell was read."))
    assert (d.state, d.corpus_sha) == ("NOT_OFFERED", None)


def test_the_declared_corpus_COMMIT_is_read_too():
    d = PROV.declared_provenance(_block(
        "Corpus at generation: PRESENT @ 8c4b608a (corpus). Figures whose "
        "predicate consults the corpus are a function of THAT tree."))
    assert (d.state, d.corpus_sha) == ("PRESENT", "8c4b608a")


def test_a_block_with_no_provenance_line_is_ITS_OWN_state():
    """The one default that must not exist, and it is not one refusal but two.

    Assuming NOT_OFFERED here would compare a block of unknown provenance against
    a corpus-withheld re-derivation, and report the difference as staleness — the
    same invisible-pointer verdict one layer up, chosen rather than inherited.

    It is a SUBCLASS because the two callers answer it differently and both are
    right: a WHOLE-BLOCK comparison already has an environment-independent answer
    (no rendering omits the provenance line, so such a block matches none of
    them), while a comparison of parsed FIGURES does not.
    """
    with pytest.raises(PROV.NoDeclaredProvenance) as e:
        PROV.declared_provenance("**621 cells: 541 ENFORCED.**\n")
    assert "declares no `Corpus at generation:` line" in str(e.value)
    assert issubclass(PROV.NoDeclaredProvenance, PROV.CannotReproduce)


def test_every_rendered_block_carries_a_provenance_line():
    """THE PREMISE the paragraph above rests on, asserted rather than believed.

    If `render()` ever stopped emitting the line unconditionally, "a block without
    one cannot match any rendering" would silently become false and `--check`
    would proceed unarranged over a block that CAN match — the invisible-pointer
    verdict, reintroduced through the door built to close it.
    """
    gen = _REPO / "tools" / "gen_flow_matrix_census.py"
    if not gen.is_file():
        pytest.skip(f"generator not present at {gen} (mirror tree)")
    src = gen.read_text(encoding="utf-8")
    body = src[src.index("def render("):]
    body = body[:body.index("\ndef ")]
    assert "out.append(corpus_identity_line())" in body, (
        "`render()` no longer appends the provenance line unconditionally; the "
        "`NoDeclaredProvenance` shortcut in `--check` is no longer sound.")
    assert "if " not in body.split("corpus_identity_line()")[0].rsplit("\n", 2)[-2], (
        "the provenance line is now emitted conditionally")


def test_an_UNKNOWN_state_word_is_NOT_MEASURED_not_silently_handled():
    with pytest.raises(PROV.CannotReproduce) as e:
        PROV.declared_provenance(_block("Corpus at generation: SOMEDAY_MAYBE"))
    assert "SOMEDAY_MAYBE" in str(e.value)


# --------------------------------------------------------------------------
# arranging it — the half that must NOT be the easy answer
# --------------------------------------------------------------------------
def test_a_NOT_OFFERED_block_is_reproduced_by_WITHHOLDING_a_bound_pointer(
        tmp_path, monkeypatch):
    """THE CASE THAT MADE main RED, and it is measurable rather than unmeasurable.

    The committed block declares NOT_OFFERED. On a corpus-mounted host the check
    can arrange exactly that — withhold the pointer for the derivation — so it
    owes the reader a real verdict and not a skip.
    """
    monkeypatch.setenv(PC.CORPUS_ENV, str(_corpus(tmp_path / "corpus")))
    seen = []
    with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")) as d:
        seen.append(os.environ.get(PC.CORPUS_ENV))
        assert d.state == "NOT_OFFERED"
        assert PC.corpus_state()[0] == PC.NOT_OFFERED
    assert seen == [None], seen
    assert os.environ[PC.CORPUS_ENV] == str(tmp_path / "corpus")


def test_a_NOT_OFFERED_block_needs_no_arrangement_when_nothing_is_bound():
    with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")) as d:
        assert d.state == "NOT_OFFERED"
        assert PC.CORPUS_ENV not in os.environ


def test_a_PRESENT_block_on_a_host_with_no_corpus_is_NOT_MEASURED():
    """Never a pass and never a fail: the cells it would re-derive are not the
    cells the block is made of, and saying "stale" about that is a false claim."""
    with pytest.raises(PROV.CannotReproduce) as e:
        with PROV.reproduce(_block("Corpus at generation: PRESENT @ 8c4b608a (c).")):
            pass
    msg = str(e.value)
    assert "PRESENT @ 8c4b608a" in msg and PC.CORPUS_ENV in msg


def test_a_DIFFERENT_corpus_is_NAMED_rather_than_accepted(tmp_path, monkeypatch):
    """Two corpora both called "the corpus" is the drift the provenance line was
    added to make visible. Accepting any mounted one deletes it again."""
    root = _corpus(tmp_path / "corpus")
    monkeypatch.setenv(PC.CORPUS_ENV, str(root))
    here = PROV.corpus_commit(root)
    with pytest.raises(PROV.CannotReproduce) as e:
        with PROV.reproduce(_block("Corpus at generation: PRESENT @ deadbee (c).")):
            pass
    assert "deadbee" in str(e.value) and here in str(e.value)


def test_the_SAME_corpus_reproduces_and_reaches_a_verdict(tmp_path, monkeypatch):
    root = _corpus(tmp_path / "corpus")
    monkeypatch.setenv(PC.CORPUS_ENV, str(root))
    sha = PROV.corpus_commit(root)
    with PROV.reproduce(_block(f"Corpus at generation: PRESENT @ {sha} (c).")) as d:
        assert d.corpus_sha == sha
        assert os.environ[PC.CORPUS_ENV] == str(root)


def test_an_UNRESOLVED_block_records_no_provenance_to_reproduce():
    with pytest.raises(PROV.CannotReproduce) as e:
        with PROV.reproduce(_block(
                "Corpus at generation: UNRESOLVED — the corpus seam could not "
                "be consulted (OSError: x).")):
            pass
    assert "UNRESOLVED" in str(e.value)


def test_the_environment_is_restored_on_the_REFUSAL_path(tmp_path, monkeypatch):
    """A refusal that leaked the toggle would hand the next check a different
    environment than the one it thinks it is in."""
    monkeypatch.setenv(PC.CORPUS_ENV, str(_corpus(tmp_path / "corpus")))
    with pytest.raises(PROV.CannotReproduce):
        with PROV.reproduce(_block("Corpus at generation: PRESENT @ deadbee (c).")):
            pass
    assert os.environ[PC.CORPUS_ENV] == str(tmp_path / "corpus")


def test_the_body_raising_still_restores_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(PC.CORPUS_ENV, str(_corpus(tmp_path / "corpus")))
    with pytest.raises(ZeroDivisionError):
        with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")):
            1 / 0
    assert os.environ[PC.CORPUS_ENV] == str(tmp_path / "corpus")


# --------------------------------------------------------------------------
# the cache is part of the environment
# --------------------------------------------------------------------------
class _FakeCache:
    def __init__(self, size):
        self._size = size

    def cache_info(self):
        class _I:
            currsize = self._size
        return _I


class _FakeCoverage:
    def __init__(self, size):
        self.collect_items = _FakeCache(size)
        self.cell_outcomes_with_record = _FakeCache(size)


def test_a_census_already_derived_under_ANOTHER_environment_is_NOT_MEASURED(
        tmp_path, monkeypatch):
    """The guard that stops this module producing the defect it removes.

    Arranging the environment after an axis has answered changes no cell — but
    `corpus_identity_line()` is read live, so the re-derived block would carry the
    DECLARED provenance over cells made under a different one. That is a
    like-with-like failure wearing this module's own output.

    The corpus is BOUND here, which is what makes the host disagree with the
    declared NOT_OFFERED. Without it this test passes on a corpus-absent host for
    the wrong reason — the derivation would have been right anyway — and would
    then never have exercised the refusal at all.
    """
    monkeypatch.setenv(PC.CORPUS_ENV, str(_corpus(tmp_path / "corpus")))
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage",
                        _FakeCoverage(1))
    with pytest.raises(PROV.CannotReproduce) as e:
        with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")):
            pass
    assert "already derived in this process" in str(e.value)
    assert "collect_items" in str(e.value)


def test_a_SECOND_consumer_asking_for_the_SAME_provenance_is_served(monkeypatch):
    """Warmth is not the question; WHICH ENVIRONMENT warmed it is.

    Three tests in `test_flow_matrix_census_freshness.py` compare against the same
    block in one session and the first of them warms the axes. Refusing the other
    two would report NOT_MEASURED over a derivation that is exactly right.
    """
    block = _block("Corpus at generation: NOT_OFFERED — x.")
    with PROV.reproduce(block):
        pass
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage",
                        _FakeCoverage(1))
    with PROV.reproduce(block) as d:
        assert d.state == "NOT_OFFERED"


def test_a_warm_cache_on_a_host_that_ALREADY_MATCHES_is_admitted(monkeypatch):
    """THE COVERAGE THIS GUARD WOULD OTHERWISE HAVE COST EVERY USER.

    On an ordinary corpus-absent checkout the block declares NOT_OFFERED and the
    host offers nothing, so whoever warmed the axes warmed them under exactly the
    declared provenance. `test_flow_matrix_coverage.py` and the census freshness
    file are BOTH in the targeted CI selection and can share one pytest process;
    refusing that would report NOT_MEASURED over a derivation that is right, and
    the check would stop running where it matters most.
    """
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage",
                        _FakeCoverage(1))
    assert PC.corpus_state()[0] == PC.NOT_OFFERED
    with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")) as d:
        assert d.state == "NOT_OFFERED"


def test_a_cache_that_cannot_be_ASKED_is_not_reported_as_cold(tmp_path,
                                                              monkeypatch):
    """"Could not read it" is not "read it and it was empty"."""
    class _Opaque:
        collect_items = object()
        cell_outcomes_with_record = object()
    monkeypatch.setenv(PC.CORPUS_ENV, str(_corpus(tmp_path / "corpus")))
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage", _Opaque)
    with pytest.raises(PROV.CannotReproduce) as e:
        with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")):
            pass
    assert "cannot be asked" in str(e.value)


def test_a_STUB_under_the_coverage_name_is_COLD_and_not_unaskable(monkeypatch):
    """MEASURED REGRESSION. `test_the_generator_cli_can_go_red_and_green` installs
    a four-function stub in `sys.modules` under the coverage module's name so the
    real generator CLI can be driven over a synthetic census in under a second. It
    names none of the axes below, has run no nested session, and is COLD.

    The first version of this guard reported it "cannot be asked" and turned that
    proof — the one test in the suite that shows `--check` can still go RED — into
    rc 2. A guard that disables the red direction of another check is worse than
    the hole it closes.
    """
    class _Stub:
        enforcement_census = staticmethod(lambda: {})
        substitution_census = staticmethod(lambda: {})
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage", _Stub)
    assert PROV._warm_caches() == []
    with PROV.reproduce(_block("Corpus at generation: NOT_OFFERED — x.")) as d:
        assert d.state == "NOT_OFFERED"


def test_a_RENAMED_axis_is_NOT_MEASURED_rather_than_silently_cold(monkeypatch):
    """One axis present and one gone is a rename in the coverage module, and
    answering "cold" to it would leave this guard blind exactly when its subject
    moved. A check that cannot fail is not a check."""
    class _Half:
        collect_items = staticmethod(lambda: None)
    _Half.collect_items.cache_info = lambda: type("I", (), {"currsize": 0})
    monkeypatch.setitem(sys.modules, "test_flow_matrix_coverage", _Half)
    warm = PROV._warm_caches()
    assert warm and "cell_outcomes_with_record" in warm[0], warm
    assert "cannot be asked" in warm[0], warm


def test_an_UNIMPORTED_coverage_module_is_COLD_by_construction(monkeypatch):
    monkeypatch.delitem(sys.modules, "test_flow_matrix_coverage", raising=False)
    assert PROV._warm_caches() == []

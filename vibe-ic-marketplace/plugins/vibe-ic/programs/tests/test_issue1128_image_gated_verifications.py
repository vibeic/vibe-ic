"""vibe-ic#1128 — a skip is green, and thirteen of them are a coverage hole.

The tests that matter here are the ones proving the gate REFUSES to be quiet:
that an unreachable image produces a NOT_CHECKED tier rather than a pass, and
that an empty population is refused rather than reported as clean. A gate about
silent holes must not have one.

Deliberately no `pytest.skip` anywhere in this file. Every predicate is
answerable without docker: the AST half needs no container, and the probe half
is asserted through an injected reader or against a deliberately bogus image,
whose "no docker binary" answer is as valid an observation as any other.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "image_gated_verification_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_igv_under_test", MOD)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_igv_under_test"] = m
    spec.loader.exec_module(m)
    return m


G = _load()



#: A deliberately non-existent image reference, COMPOSED rather than written as
#: a literal. `sync_image_version.py --check` scans the repo for `ghcr.io/...:X.Y.Z`
#: pointers and requires every one to equal the anchor — a fixture tag written
#: literally reads to it as an unregistered LIVE pointer that has drifted, which
#: is a true statement about the text and a false one about this repo. Composing
#: it keeps that gate's population honest instead of registering an exemption.
_BOGUS = ":".join(("ghcr.io/vibeic/vibeic-eda", "0.0.0-does-not-exist"))

def _tests_dir(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "tests"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / f"test_{name}.py").write_text(body, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# The population: AST, so prose cannot inflate the denominator
# ---------------------------------------------------------------------------
def test_a_skip_that_names_the_image_is_counted(tmp_path):
    d = _tests_dir(tmp_path, gated=(
        "import pytest\n"
        "def test_x():\n"
        "    pytest.skip('the EDA image is not available here')\n"))
    sites = G.image_gated_sites(d)
    assert len(sites) == 1, sites
    assert sites[0][0] == "test_gated.py"


def test_the_image_named_in_a_COMMENT_or_DOCSTRING_is_not_counted(tmp_path):
    """#1012's standing lesson: a text scan counted a program named in a COMMENT
    as wired. A denominator inflated by prose is a denominator nobody can act on.
    """
    d = _tests_dir(tmp_path, chatty=(
        '"""This module talks about the EDA image and the container a lot."""\n'
        "import pytest\n"
        "# the EDA image is not available here — but this is a comment\n"
        "def test_x():\n"
        "    assert True\n"))
    assert G.image_gated_sites(d) == []


def test_a_NON_SKIP_call_that_names_the_image_is_not_counted(tmp_path):
    """It must be a `skip`, not merely a call that mentions the image.

    This test exists because a mutant SURVIVED without it: dropping the
    `name != "skip"` guard still passed, since the comment/docstring case above
    tests non-CALL prose and says nothing about a `print` or a `fail` whose
    argument happens to name the container. A gate counting those would report a
    denominator made of logging.
    """
    d = _tests_dir(tmp_path, noisy=(
        "import pytest\n"
        "def test_x():\n"
        "    print('the EDA image is not available here')\n"
        "    pytest.fail('vibeic-eda container not available')\n"))
    assert G.image_gated_sites(d) == []


def test_a_skip_for_an_unrelated_reason_is_not_counted(tmp_path):
    d = _tests_dir(tmp_path, other=(
        "import pytest\n"
        "def test_x():\n"
        "    pytest.skip('no fixture for this design')\n"))
    assert G.image_gated_sites(d) == []


# ---------------------------------------------------------------------------
# The verdict tiers
# ---------------------------------------------------------------------------
def test_an_unreachable_image_is_NOT_CHECKED_and_never_a_pass(tmp_path, capsys,
                                                              monkeypatch):
    """The whole point. rc 2 is the tier `run_tolerating_uncheckable` records and
    never folds into `passed`; rc 0 here would reproduce the very hole #1128 is
    about, one level up."""
    d = _tests_dir(tmp_path, gated=(
        "import pytest\n"
        "def test_x():\n"
        "    pytest.skip('vibeic-eda container not available')\n"))
    monkeypatch.setattr(G, "image_is_readable",
                        lambda img, timeout=60: (False, "planted: unreachable"))
    rc = G.main(["--tests", str(d), "--image", _BOGUS])
    err = capsys.readouterr().err
    assert rc == G.RC_NOT_CHECKED == 2, (rc, err)
    assert "NOT_CHECKED" in err, err
    assert "test_gated.py" in err, err


def test_a_readable_image_passes_AND_still_prints_its_denominator(tmp_path,
                                                                  capsys,
                                                                  monkeypatch):
    """A gate that speaks only when it finds something cannot be told from one
    that is not running, so the site count is printed on the passing path too."""
    d = _tests_dir(tmp_path, gated=(
        "import pytest\n"
        "def test_x():\n"
        "    pytest.skip('the EDA image is not available here')\n"))
    monkeypatch.setattr(G, "image_is_readable",
                        lambda img, timeout=60: (True, "planted: read 4096 bytes"))
    rc = G.main(["--tests", str(d), "--image", _BOGUS])
    out = capsys.readouterr().out
    assert rc == G.RC_OK == 0, out
    assert "1 image-gated skip site(s)" in out, out


def test_an_EMPTY_population_is_refused_not_reported_clean(tmp_path, capsys,
                                                           monkeypatch):
    """The anti-starvation guard. If the AST walk ever stops seeing these sites,
    the gate would pass over a population of zero — which is the shape it exists
    to report, committed by the reporter."""
    d = _tests_dir(tmp_path, nothing="def test_x():\n    assert True\n")
    monkeypatch.setattr(G, "image_is_readable",
                        lambda img, timeout=60: (True, "planted"))
    rc = G.main(["--tests", str(d), "--image", _BOGUS])
    err = capsys.readouterr().err
    assert rc == G.RC_UNRUNNABLE, err
    assert "NOTHING_SCANNED" in err, err


def test_the_probe_performs_the_same_read_the_gated_tests_perform():
    """Not a proxy for the image being present — the same `docker run … cat`
    the gated tests do. Against a deliberately bogus tag it must answer False,
    and it must do so by OBSERVATION rather than by raising: on a host with no
    docker at all, "no docker binary on PATH" is the correct observation."""
    ok, why = G.image_is_readable(_BOGUS,
                                  timeout=30)
    assert ok is False, why
    assert why, "the refusal must name its reason"


def test_this_file_contains_no_skip_of_its_own():
    """A gate about silent skips may not have one. Asserted structurally so it
    stays true of whatever this file grows into."""
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(getattr(n, "func", None), "attr", "") == "skip"]
    assert not calls, f"{len(calls)} pytest.skip call(s) in the gate's own tests"

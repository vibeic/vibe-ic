"""`protected_landing_manifest_author` must render what the VERIFIER accepts.

The program exists because three hand-authored manifests in a row were refused
by `protected_landing_transition.parse_manifest`, so the one property worth
asserting is that its output goes through that same parser -- not that the JSON
looks plausible.

This file lives under `tools/` on purpose: it is covered by the repo-tools
landing arm, which is the arm that was reporting the malformed manifest.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_AUTHOR = _ROOT / "tools" / "ci" / "protected_landing_manifest_author.py"
_MANIFEST = "tools/ci/protected_landing_transition.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def author():
    return _load(_AUTHOR, "_test_manifest_author")


@pytest.fixture(scope="module")
def transition():
    return _load(_ROOT / "tools" / "ci" / "protected_landing_transition.py",
                 "_test_protected_landing_transition")


@pytest.fixture(scope="module")
def head() -> str:
    proc = subprocess.run(["git", "-C", str(_ROOT), "rev-parse", "HEAD"],
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        pytest.skip("this checkout is not a git work tree, so the tuple this "
                    "program observes is UNAVAILABLE here -- not verified")
    return proc.stdout.strip()


def _a_protected_path(transition_mod) -> str:
    manifest = json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))
    return manifest["paths"][0]["path"]


def _rendered(author, head, tmp_path, transition_mod, *, path=None):
    subject = path or _a_protected_path(transition_mod)
    future = tmp_path / "future_bytes"
    future.write_bytes((_ROOT / subject).read_bytes() + b"\n# future\n")
    return author.render(repo=_ROOT, commit=head,
                         transition_id="junattr-render-probe-v1",
                         current_id="probe-current", next_id="probe-next",
                         moves={subject: future})


def test_the_rendered_manifest_is_one_the_verifier_parses(
        author, transition, head, tmp_path):
    """The claim. `render` already calls the parser; this drives it again from
    the SERIALISED bytes, because what lands is the file and not the object."""
    manifest = _rendered(author, head, tmp_path, transition)
    raw = author.serialise(manifest)
    _algorithm, oid_len = transition._object_format(_ROOT)
    parsed = transition.parse_manifest(
        transition.strict_loads(raw, what="rendered manifest"), oid_len)
    assert parsed["transition_id"] == "junattr-render-probe-v1"
    assert parsed["current"]["id"] != parsed["next"]["id"]


def test_current_is_the_tuple_the_named_commit_actually_holds(
        author, transition, head, tmp_path):
    """`current` is OBSERVED, never copied from the manifest being replaced --
    which is the exact error that let two protected files drift unrecorded."""
    manifest = _rendered(author, head, tmp_path, transition)
    algorithm, oid_len = transition._object_format(_ROOT)
    live = json.loads((_ROOT / _MANIFEST).read_text(encoding="utf-8"))
    observed = transition._observe_files(
        _ROOT, head, live["paths"], algorithm, oid_len)
    assert manifest["current"]["files"] == observed


def test_next_differs_in_exactly_the_paths_that_were_moved(
        author, transition, head, tmp_path):
    manifest = _rendered(author, head, tmp_path, transition)
    moved = [row["path"] for row, other
             in zip(manifest["current"]["files"], manifest["next"]["files"])
             if row != other]
    assert moved == [_a_protected_path(transition)]


def test_a_manifest_that_moves_nothing_is_refused_with_its_reason(
        author, head):
    """The shape three commits landed. It must not be renderable by accident."""
    with pytest.raises(Exception) as caught:
        author.render(repo=_ROOT, commit=head, transition_id="probe-v1",
                      current_id="a", next_id="b", moves={})
    assert "no settled manifest" in str(caught.value)


def test_a_move_naming_an_unprotected_path_is_refused(
        author, head, tmp_path):
    future = tmp_path / "future"
    future.write_text("x", encoding="utf-8")
    with pytest.raises(Exception) as caught:
        author.render(repo=_ROOT, commit=head, transition_id="probe-v1",
                      current_id="a", next_id="b",
                      moves={"README.md": future})
    assert "does not protect" in str(caught.value)


def test_a_move_to_the_bytes_already_in_the_tree_is_refused(
        author, transition, head, tmp_path):
    """A no-op move renders a manifest the parser refuses (`next tuple does not
    differ`), so it is refused HERE, where the author can still see why."""
    subject = _a_protected_path(transition)
    same = tmp_path / "same"
    same.write_bytes((_ROOT / subject).read_bytes())
    with pytest.raises(Exception) as caught:
        author.render(repo=_ROOT, commit=head, transition_id="probe-v1",
                      current_id="a", next_id="b", moves={subject: same})
    assert "moves nothing" in str(caught.value)


def test_the_serialised_shape_round_trips_the_manifest_in_the_tree(author):
    """A re-render of an unchanged tuple must produce NO diff, or every author
    would have to eyeball a whole-file reformat to find their own change."""
    raw = (_ROOT / _MANIFEST).read_bytes()
    assert author.serialise(json.loads(raw)) == raw


def test_the_cli_refuses_a_malformed_move_argument(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_AUTHOR), "--repo", str(_ROOT),
         "--transition-id", "p", "--current-id", "a", "--next-id", "b",
         "--next-file", "no-equals-sign"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "PATH=FILE" in proc.stderr


# ---------------------------------------------------------------------------
# THE REGISTER IS DERIVED FROM THE VERIFIER, NOT MAINTAINED BY HAND.
#
# `paths` and `runner` were copied verbatim out of whatever manifest was
# already in the tree, so the register could only ever be as current as the
# last person who remembered to edit it -- at v1.13.3 that was v1.12.39, and
# `test_phase_b_activated_parity.py` had been 3-red on main ever since, which
# blocks EVERY protected-file change.
#
# A path is protected because the verifier READS it, so the verifier is the
# source of truth. Both roles are already declared there and are what these
# tests bind to.
# ---------------------------------------------------------------------------


def test_the_protected_set_is_what_the_verifier_executes(transition):
    """Derived, and derived from the two sets the verifier enforces."""
    derived = {row["path"]: tuple(row["roles"])
               for row in transition.derived_paths()}
    assert derived, "the derivation produced no protected set at all"
    for path in transition.RUNTIME_PATHS:
        assert "runtime" in derived[path], path
    for path in transition.REQUIRED_AUTHORITY_PATHS:
        assert "authority" in derived[path], path
    assert set(derived) == (set(transition.RUNTIME_PATHS)
                            | set(transition.REQUIRED_AUTHORITY_PATHS))
    for path, roles in derived.items():
        assert list(roles) == sorted(set(roles)), path
        assert set(roles) <= transition.ROLE_VALUES, path


def test_the_derivation_reproduces_the_register_in_the_tree(author, transition):
    """A no-op TODAY, which is what makes it safe to adopt.

    MEASURED at v1.13.3: the hand-kept register held exactly this union -- 52
    paths, 41 authority-only, 4 runtime-only, 7 both, zero surplus and zero
    missing -- so the copy was already redundant and was only waiting to
    disagree. If this ever fails, the register and the verifier have parted
    company and THAT is the finding.
    """
    live = json.loads((_ROOT / _MANIFEST).read_bytes())
    assert transition.derived_paths() == live["paths"]
    assert transition.derived_runner() == live["runner"]


def test_the_derived_runner_is_one_the_verifier_accepts(transition):
    """Built from the same profile `_runner_profile` validates against, so the
    author cannot render a runner the verifier would refuse."""
    assert transition._runner_profile(transition.derived_runner()) == \
        transition.derived_runner()


def test_a_silently_shrinking_protected_set_is_refused(author, transition):
    """THE GUARD.  A quiet contraction is worse than a stale register."""
    full = transition.derived_paths()
    victim = sorted(transition.REQUIRED_AUTHORITY_PATHS)[0]
    shrunk = [row for row in full if row["path"] != victim]
    author.refuse_a_shrink(full, full)            # a no-op set is fine
    with pytest.raises(Exception) as caught:
        author.refuse_a_shrink(full, shrunk)
    assert victim in str(caught.value), caught.value
    assert "SMALLER" in str(caught.value), caught.value


def test_a_withdrawal_with_a_recorded_reason_is_allowed(author, transition,
                                                        monkeypatch):
    """The guard is not a wall: it asks for the reason, in the same commit."""
    full = transition.derived_paths()
    victim = sorted(transition.REQUIRED_AUTHORITY_PATHS)[0]
    shrunk = [row for row in full if row["path"] != victim]
    monkeypatch.setattr(author, "WITHDRAWN",
                        {victim: "probe: the verifier no longer reads it"})
    author.refuse_a_shrink(full, shrunk)          # named, therefore allowed


def test_the_guard_reads_the_previous_register_defensively(author, transition):
    """Rows a stale file may hold that are not `{"path": str}` are ignored,
    never crashed on: the guard runs against whatever is already in the tree."""
    author.refuse_a_shrink([{"nope": 1}, "junk", None], transition.derived_paths())

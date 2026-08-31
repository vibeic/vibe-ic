"""The author must be able to EMIT the move the verifier learned to read.

WHY THIS FILE EXISTS.  `manifest.moves` and the RENAME operation gave the
VERIFIER a way to express a protected path changing its name.  Nothing gave the
AUTHOR one: `render` took `moves` -- future BYTES at a fixed path -- and had no
argument that could put a `moves` row in the object it hands to
`parse_manifest`.  MEASURED on `origin/main cd0a98dd8`, before this change:

    render(..., renames={old: new})   TypeError: render() got an unexpected
                                      keyword argument 'renames'
    protected_landing_manifest_author.py --move OLD=NEW
                                      error: unrecognized arguments: --move

So the only manifest that could authorise a rename was a hand-edited one, and a
hand-edited manifest is the malformation the program's own docstring exists to
describe.  A capability only one side can speak is not a capability.

EVERY CASE HERE FAILS AGAINST THE PRE-CHANGE AUTHOR except the two negative
controls, which pin the behaviour that must NOT move: a render that declares no
rename emits no `moves` key at all, and `refuse_a_shrink` still reports a path
that simply vanished.
"""
from __future__ import annotations

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
    return _load(_AUTHOR, "_test_manifest_author_move")


@pytest.fixture(scope="module")
def transition():
    return _load(_ROOT / "tools" / "ci" / "protected_landing_transition.py",
                 "_test_protected_landing_transition_move")


@pytest.fixture(scope="module")
def head() -> str:
    proc = subprocess.run(["git", "-C", str(_ROOT), "rev-parse", "HEAD"],
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        pytest.skip("this checkout is not a git work tree, so the tuple this "
                    "program observes is UNAVAILABLE here -- not verified")
    return proc.stdout.strip()


def _a_runtime_path(transition_mod) -> str:
    """DERIVED, never typed.

    `runtime` is the role worth moving because its set is compared for EXACT
    equality; and a test that hard-codes the name of the file it renames goes
    stale the first time that file is renamed, which is the disease the whole
    `moves` capability treats.
    """
    return sorted(transition_mod.RUNTIME_PATHS)[-1]


def _destination(source: str) -> str:
    return source.rsplit("/", 1)[0] + "/zz_author_move_probe.py"


def _render(author, head, **kwargs):
    base = dict(repo=_ROOT, commit=head,
                transition_id="junattr-move-probe-v1",
                current_id="probe-current", next_id="probe-next", moves={})
    base.update(kwargs)
    return author.render(**base)


# --------------------------------------------------------------------------
# NEGATIVE CONTROLS.  These pass against the pre-change author too, and that is
# the point: they pin what must NOT move.
# --------------------------------------------------------------------------
def test_a_render_that_declares_no_rename_carries_no_moves_key(
        author, transition, head, tmp_path):
    """The identity case must be byte-for-byte what it was, or the new limb is
    reachable from a manifest that declares nothing -- which is how a gate
    acquires a hole nobody is looking at."""
    subject = _a_runtime_path(transition)
    future = tmp_path / "future_bytes"
    future.write_bytes((_ROOT / subject).read_bytes() + b"\n# future\n")
    manifest = _render(author, head, moves={subject: future})
    assert "moves" not in manifest
    assert [row["path"] for row in manifest["next"]["files"]] == \
           [row["path"] for row in manifest["current"]["files"]]


def test_a_path_that_simply_vanished_is_still_reported(author):
    """`refuse_a_shrink` must keep refusing the thing it was written for: a
    declared move is an exception, an unexplained disappearance is not."""
    previous = [{"path": "a"}, {"path": "b"}]
    with pytest.raises(author.Refusal) as excinfo:
        author.refuse_a_shrink(previous, [{"path": "a"}])
    assert "b" in str(excinfo.value)


# --------------------------------------------------------------------------
# THE CAPABILITY.
# --------------------------------------------------------------------------
def test_a_declared_rename_is_emitted_and_the_verifier_parses_it(
        author, transition, head):
    subject = _a_runtime_path(transition)
    destination = _destination(subject)
    manifest = _render(author, head, renames={subject: destination})
    assert manifest["moves"] == [{"from": subject, "to": destination}]
    raw = author.serialise(manifest)
    _algorithm, oid_len = transition._object_format(_ROOT)
    parsed = transition.parse_manifest(
        transition.strict_loads(raw, what="rendered manifest"), oid_len)
    assert parsed["moves"] == [{"from": subject, "to": destination}]


def test_next_covers_the_moved_path_set_and_current_the_old_one(
        author, transition, head):
    """The two states are photographed at DIFFERENT path sets, which is the
    whole content of a rename: `current` is where the bytes are, `next` is
    where they are going."""
    subject = _a_runtime_path(transition)
    destination = _destination(subject)
    manifest = _render(author, head, renames={subject: destination})
    current = [row["path"] for row in manifest["current"]["files"]]
    nxt = [row["path"] for row in manifest["next"]["files"]]
    assert subject in current and destination not in current
    assert destination in nxt and subject not in nxt
    assert nxt == sorted(nxt)
    assert nxt == transition.apply_moves(current, manifest["moves"])


def test_a_pure_rename_carries_the_record_across_unchanged(
        author, transition, head):
    """`git mv` does not rewrite a file, so the register must not say it did:
    every field except `path` survives."""
    subject = _a_runtime_path(transition)
    destination = _destination(subject)
    manifest = _render(author, head, renames={subject: destination})
    was = next(row for row in manifest["current"]["files"]
               if row["path"] == subject)
    now = next(row for row in manifest["next"]["files"]
               if row["path"] == destination)
    assert {**was, "path": destination} == now


def test_future_bytes_are_named_at_the_path_the_tree_will_hold(
        author, transition, head, tmp_path):
    """A rename that also edits is the real case -- the renamed module's own
    imports change with it -- so the bytes are keyed on the DESTINATION."""
    subject = _a_runtime_path(transition)
    destination = _destination(subject)
    future = tmp_path / "future_bytes"
    future.write_bytes((_ROOT / subject).read_bytes() + b"\n# renamed\n")
    manifest = _render(author, head, renames={subject: destination},
                       moves={destination: future})
    now = next(row for row in manifest["next"]["files"]
               if row["path"] == destination)
    was = next(row for row in manifest["current"]["files"]
               if row["path"] == subject)
    assert now["size"] == was["size"] + len(b"\n# renamed\n")
    assert now["sha256"] != was["sha256"]


# --------------------------------------------------------------------------
# FALSIFICATION.  Each refusal must NAME what is wrong.
# --------------------------------------------------------------------------
def test_a_rename_onto_an_already_protected_path_is_refused(
        author, transition, head):
    subject = _a_runtime_path(transition)
    other = sorted(transition.RUNTIME_PATHS - {subject})[0]
    with pytest.raises(author.Refusal) as excinfo:
        _render(author, head, renames={subject: other})
    assert "already-protected path" in str(excinfo.value)


def test_a_rename_of_an_unprotected_path_is_refused(author, head):
    with pytest.raises(author.Refusal) as excinfo:
        _render(author, head,
                renames={"tools/ci/not_protected_at_all.py": "tools/ci/x.py"})
    assert "does not protect" in str(excinfo.value)


def test_a_reobservation_cannot_declare_a_rename(author, transition, head):
    """`--no-move` authorises NOTHING, so it may not hand out a destination."""
    subject = _a_runtime_path(transition)
    with pytest.raises(author.Refusal) as excinfo:
        _render(author, head, renames={subject: _destination(subject)},
                no_move=True)
    assert "--no-move" in str(excinfo.value) and "--move" in str(excinfo.value)


def test_future_bytes_for_a_path_the_move_removes_are_refused(
        author, transition, head, tmp_path):
    """Once a path is renamed away it is not in the set the tree will hold, so
    naming its future bytes is naming a file that will not exist."""
    subject = _a_runtime_path(transition)
    future = tmp_path / "future_bytes"
    future.write_bytes(b"anything\n")
    with pytest.raises(author.Refusal) as excinfo:
        _render(author, head, renames={subject: _destination(subject)},
                moves={subject: future})
    assert "does not protect" in str(excinfo.value)


# --------------------------------------------------------------------------
# THE SHRINK GUARD READS THE REGISTER, NOT A HAND-KEPT LIST.
# --------------------------------------------------------------------------
def test_a_declared_move_that_arrived_is_not_a_shrink(author):
    previous = [{"path": "old.py"}, {"path": "kept.py"}]
    derived = [{"path": "new.py"}, {"path": "kept.py"}]
    author.refuse_a_shrink(previous, derived,
                           [{"from": "old.py", "to": "new.py"}])


def test_a_declared_move_that_lost_its_file_is_still_a_shrink(author):
    """A rename whose destination is NOT derived is a deletion that happens to
    have been announced."""
    previous = [{"path": "old.py"}, {"path": "kept.py"}]
    derived = [{"path": "kept.py"}]
    with pytest.raises(author.Refusal) as excinfo:
        author.refuse_a_shrink(previous, derived,
                               [{"from": "old.py", "to": "new.py"}])
    assert "old.py" in str(excinfo.value)


def test_withdrawn_is_empty_so_no_rename_is_being_silenced_by_it(author):
    """The whole point of teaching the guard about declared moves is that
    renames stop being written into `WITHDRAWN`, which is a record of
    decisions and not a place to put paths that are still protected."""
    assert author.WITHDRAWN == {}


# --------------------------------------------------------------------------
# THE COMMAND LINE, because that is what an operator runs.
# --------------------------------------------------------------------------
def test_the_cli_accepts_move_and_writes_a_manifest_carrying_it(
        transition, head, tmp_path):
    subject = _a_runtime_path(transition)
    destination = _destination(subject)
    out = tmp_path / "manifest.json"
    proc = subprocess.run(
        [sys.executable, str(_AUTHOR), "--repo", str(_ROOT),
         "--commit", head, "--transition-id", "junattr-move-cli-v1",
         "--current-id", "cli-current", "--next-id", "cli-next",
         "--move", f"{subject}={destination}", "--out", str(out)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["moves"] == [{"from": subject, "to": destination}]


def test_the_cli_refuses_move_together_with_no_move(transition, head, tmp_path):
    subject = _a_runtime_path(transition)
    proc = subprocess.run(
        [sys.executable, str(_AUTHOR), "--repo", str(_ROOT),
         "--commit", head, "--transition-id", "junattr-move-cli-v1",
         "--current-id", "cli-current", "--next-id", "cli-next",
         "--move", f"{subject}={_destination(subject)}", "--no-move",
         "--out", str(tmp_path / "manifest.json")],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "REFUSE" in proc.stderr

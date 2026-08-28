"""The authority-pin rule: the report that has to reach the author.

ADVISORY by design, so the red is proved through `--strict`. A gate that
blocked here would refuse the very change the manifest exists to record.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "content_pinned_authority_verified_only_at_merge.py")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tree(files: dict, pins: dict) -> Path:
    """`files`: rel -> bytes on disk. `pins`: state -> {rel: bytes pinned}."""
    root = Path(tempfile.mkdtemp(prefix="cpa_"))
    (root / ".git").mkdir()
    (root / "vibe-ic-marketplace").mkdir()
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    doc = {"kind": "vibeic.protected-landing-transition", "schema": 1}
    for state, pinned in pins.items():
        doc[state] = {"id": f"{state}-id",
                      "files": [{"path": rel, "sha256": _sha(body)}
                                for rel, body in pinned.items()]}
    m = root / "tools" / "ci" / "protected_landing_transition.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps(doc) + "\n")
    return root


def _run(root: Path, *extra):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), *extra],
        capture_output=True, text=True)


_A = b"authority body A\n"
_B = b"authority body B\n"
_EDITED = b"authority body A, edited on this branch\n"


def test_an_edited_authority_path_is_reported():
    """NEGATIVE CONTROL, via --strict: the obligation must be visible HERE."""
    root = _tree({"tools/ci/x.sh": _EDITED},
                 {"current": {"tools/ci/x.sh": _A},
                  "next": {"tools/ci/x.sh": _B}})
    r = _run(root, "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "tools/ci/x.sh" in r.stdout
    assert "neither pinned state" in r.stdout


def test_the_same_mismatch_is_advisory_by_default():
    """It must stay advisory: blocking refuses the change it exists to record."""
    root = _tree({"tools/ci/x.sh": _EDITED},
                 {"current": {"tools/ci/x.sh": _A},
                  "next": {"tools/ci/x.sh": _B}})
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[WARN]" in r.stdout
    assert "Re-render the manifest" in r.stdout
    assert "protected_landing_transition.py" in r.stdout, (
        "the report must name the tool that renders the manifest")


def test_a_tree_sitting_in_the_current_state_is_clean():
    root = _tree({"tools/ci/x.sh": _A},
                 {"current": {"tools/ci/x.sh": _A},
                  "next": {"tools/ci/x.sh": _B}})
    r = _run(root, "--strict")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[PASS]" in r.stdout


def test_a_tree_sitting_in_the_next_state_is_also_clean():
    """A transition names two states; sitting in EITHER is consistent."""
    root = _tree({"tools/ci/x.sh": _B},
                 {"current": {"tools/ci/x.sh": _A},
                  "next": {"tools/ci/x.sh": _B}})
    r = _run(root, "--strict")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_an_absent_pinned_path_is_its_own_outcome():
    """A deleted authority file and an edited one are different obligations."""
    root = _tree({}, {"current": {"tools/ci/x.sh": _A},
                      "next": {"tools/ci/x.sh": _A}})
    r = _run(root, "--strict")
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"
    assert "ABSENT from the tree" in r.stdout


def test_a_missing_manifest_is_undetermined_not_a_pass():
    root = Path(tempfile.mkdtemp(prefix="cpa_"))
    (root / ".git").mkdir()
    (root / "vibe-ic-marketplace").mkdir()
    r = _run(root)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "CANNOT DETERMINE" in r.stderr


def test_an_unreadable_manifest_is_undetermined_not_a_pass():
    root = _tree({}, {"current": {}, "next": {}})
    bad = root / "bad.json"
    bad.write_text("{not json")
    r = _run(root, "--manifest", str(bad))
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_runs_advisory_and_states_its_denominator():
    root = Path(__file__).resolve().parents[5]
    if not (root / "tools" / "ci" / "protected_landing_transition.json").is_file():
        pytest.skip("no manifest in this checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "pinned paths:" in r.stdout, (
        "an advisory that cannot say how many paths it hashed has not hashed "
        "any")

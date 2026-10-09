"""Fail-closed path containment checks for native execution outputs."""
from pathlib import Path
import sys

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_modes as em  # noqa: E402


def test_safe_relative_path_rejects_symlink_root(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "root"
    root.symlink_to(target, target_is_directory=True)

    assert em._safe_relative_path(root, "reports/result.json") is None


def test_safe_relative_path_rejects_symlink_parent(tmp_path):
    target_parent = tmp_path / "target-parent"
    target_parent.mkdir()
    (target_parent / "root").mkdir()
    parent = tmp_path / "parent"
    parent.symlink_to(target_parent, target_is_directory=True)

    assert em._safe_relative_path(parent / "root", "reports/result.json") is None


def test_safe_relative_path_preserves_root_and_child_containment(tmp_path):
    root = tmp_path / "root"
    (root / "reports").mkdir(parents=True)

    expected = root / "reports" / "result.json"
    assert em._safe_relative_path(root, "reports/result.json") == expected
    assert em._safe_relative_path(root, "../outside.txt") is None

    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "reports" / "link").symlink_to(outside, target_is_directory=True)
    assert em._safe_relative_path(root, "reports/link/result.json") is None

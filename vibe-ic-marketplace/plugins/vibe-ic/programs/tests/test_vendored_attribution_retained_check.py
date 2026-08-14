"""vibe-ic#1043 — third-party source that ships must ship with its record.

The issue is a licensing obligation: a withdrawal deleted `SOURCE_MANIFEST.md`
files while the Apache-2.0 RTL they attribute stayed tracked. Apache-2.0
§4(b)/§4(d) attach to distributing the WORK, so withdrawing a run does not
withdraw the duty — the obligation does not travel with the evidence.

What made it worth a program rather than a review note is that **nothing could
tell**. The records are emitted and read back for RTL reconciliation; no gate
ever asked whether a licensed file that is still tracked still has one.

Every test below builds a real git repository in `tmp_path` and drives the
shipped `main()`. Nothing re-implements the predicate.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import vendored_attribution_retained_check as V  # noqa: E402

APACHE = "// SPDX-License-Identifier: Apache-2.0\nmodule m; endmodule\n"
PLAIN = "module m; endmodule\n"


def _git(root: Path, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    return root


def _w(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def _commit(root: Path):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


def _run(root: Path, scope: str = "bd") -> int:
    return V.main([str(root), "--scope", scope])


# ═══════════════ the #1043 scenario, as a verdict ═══════════════
def test_deleting_the_record_while_the_code_stays_is_caught(tmp_path, capsys):
    """THE ISSUE, reproduced end to end.

    A licensed file and its record are committed together and the gate is
    green. The record is then deleted while the code stays — which is exactly
    what a withdrawal does to a manifest that happens to sit inside a withdrawn
    root — and the gate must go red.
    """
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/SOURCE_MANIFEST.md", "upstream: somewhere, Apache-2.0\n")
    _w(root, "bd/ic/x/rtl/vendored.v", APACHE)
    _commit(root)
    assert _run(root) == 0, capsys.readouterr().out

    (root / "bd/ic/x/SOURCE_MANIFEST.md").unlink()
    _commit(root)
    assert _run(root) == 1
    out = capsys.readouterr().out
    assert "bd/ic/x/rtl/vendored.v" in out
    assert "Apache-2.0" in out


def test_removing_the_code_too_is_lawful_and_stays_green(tmp_path, capsys):
    """THE OTHER LAWFUL OPTION, and the guard that stops this gate from
    reading as 'never delete a manifest'.

    Deleting the record AND the code it attributes withdraws the distribution,
    which discharges the duty. The gate must not object — otherwise it would
    forbid the very withdrawal the owner ruled for.
    """
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/SOURCE_MANIFEST.md", "upstream: somewhere, Apache-2.0\n")
    _w(root, "bd/ic/x/rtl/vendored.v", APACHE)
    _commit(root)

    (root / "bd/ic/x/SOURCE_MANIFEST.md").unlink()
    (root / "bd/ic/x/rtl/vendored.v").unlink()
    _commit(root)
    assert _run(root) == 0, capsys.readouterr().out


# ═══════════════ the coverage rule ═══════════════
def test_an_ancestor_record_covers_a_nested_file(tmp_path, capsys):
    """Records sit at the IC root in this tree; the code sits several levels
    down. Requiring one per directory would manufacture findings against every
    shipped manifest."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/SOURCE_MANIFEST.md", "upstream\n")
    _w(root, "bd/ic/x/a/b/c/deep.v", APACHE)
    _commit(root)
    assert _run(root) == 0, capsys.readouterr().out


def test_a_manifest_at_the_scan_root_does_not_cover_the_world(tmp_path, capsys):
    """A check that one added path can switch off is a ban wearing a checkmark.

    `bd/SOURCE_MANIFEST.md` must NOT satisfy `bd/ic/x/rtl/vendored.v`, or the
    whole corpus becomes covered by a single file nobody reads.
    """
    root = _repo(tmp_path / "r")
    _w(root, "bd/SOURCE_MANIFEST.md", "a record covering everything\n")
    _w(root, "bd/ic/x/rtl/vendored.v", APACHE)
    _commit(root)
    assert _run(root) == 1, capsys.readouterr().out
    assert "bd/ic/x/rtl/vendored.v" in capsys.readouterr().out


def test_an_unlicensed_file_is_not_the_gates_business(tmp_path, capsys):
    """No SPDX header, no claim to trace. Judging every file would turn a
    licensing gate into a documentation gate."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/rtl/authored.v", PLAIN)
    _commit(root)
    assert _run(root) == 0, capsys.readouterr().out


def test_a_json_record_counts_as_a_record(tmp_path, capsys):
    """This tree ships `SOURCE_MANIFEST.json` as well as `.md` — the gate keys
    on the name, not on one extension."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/SOURCE_MANIFEST.json", "{}\n")
    _w(root, "bd/ic/x/rtl/vendored.v", APACHE)
    _commit(root)
    assert _run(root) == 0, capsys.readouterr().out


def test_the_licence_id_is_reported_not_matched(tmp_path, capsys):
    """chip-AGNOSTIC / no-list: the gate never compares the id against a
    permitted set. An id it has never seen is still a licence, and is still
    reported by name."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/rtl/v.v",
       "// SPDX-License-Identifier: Zaphod-1.0\nmodule m; endmodule\n")
    _commit(root)
    assert _run(root) == 1
    assert "Zaphod-1.0" in capsys.readouterr().out


def test_an_untracked_file_carries_no_obligation(tmp_path, capsys):
    """The duty attaches to what is DISTRIBUTED. A scratch copy in the working
    tree is not distributed, and a filesystem walk would make the verdict a
    property of the author's build directory."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/rtl/authored.v", PLAIN)
    _commit(root)
    _w(root, "bd/ic/x/rtl/scratch.v", APACHE)      # never added
    assert _run(root) == 0, capsys.readouterr().out


def test_an_empty_scope_discloses_that_it_checked_nothing(tmp_path, capsys):
    """A green over an empty population is the failure mode this whole campaign
    is about. It must say so rather than print PASS."""
    root = _repo(tmp_path / "r")
    _w(root, "bd/ic/x/rtl/authored.v", PLAIN)
    _commit(root)
    assert V.main([str(root), "--scope", "nonexistent"]) == 0
    assert "VACUOUS_PASS" in capsys.readouterr().out


# ═══════════════ the shipped tree ═══════════════
def test_the_shipped_corpus_is_covered():
    """The anchor. Runs the gate against this repository, not a fixture.

    Measured on `947547716` before the fix: 525 licence-declaring files, ONE
    uncovered — 152,616 lines of `Copyright 2020 The SkyWater PDK Authors`
    under an IC root with no record at all. It is closed by
    `benchmark-data/ic/spm/SOURCE_MANIFEST.md` in the same commit as this gate.
    """
    repo = PROGRAMS.parents[3]
    if not (repo / ".git").exists() or not (repo / "benchmark-data").is_dir():
        pytest.skip("not the source tree (flattened plugin cache)")
    res = V.scan(repo, "benchmark-data")
    assert res["licensed"] > 0, (
        "the shipped corpus declares no licences at all — this anchor would "
        "pass vacuously and the gate would be unmeasured")
    assert not res["uncovered"], (
        f"{len(res['uncovered'])} licence-declaring file(s) ship with no "
        f"attribution record: {[u['path'] for u in res['uncovered'][:10]]}")

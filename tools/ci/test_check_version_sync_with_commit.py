"""tools/ci/test_check_version_sync_with_commit.py — pytest harness for the
commit-msg ↔ plugin/marketplace version-sync hook.

Pins the #422 fix (ORGANIC-20260606-version-claim-marker-window-off-by-v):
`first_version()` sliced its historical-marker look-back window at
`m.start()` — the optional 'v' itself — so every marker that carried a
trailing " v" ("from v", "fixes v", "since v", "replaces v") could NEVER
appear inside the window; "iter-5 from v0.2.50" hard-failed despite the
documented exemption (and the bare "from 0.2.50" spelling failed too,
since no 'v'-free markers existed). Fixed by slicing the window at the
DIGITS (`m.start(1)`) and normalising the markers to their 'v'-free form,
covering both spellings.

Hermetic: each test copies the real script into a tmp tree with synthetic
plugin.json + marketplace.json at the canonical relative paths, then feeds
a commit-message file as $1 — no git fixtures, no repo state.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

REAL_SCRIPT = Path(__file__).resolve().parent / "check_version_sync_with_commit.sh"


def _stage(tmp_path: Path, version: str = "9.9.9") -> Path:
    script = tmp_path / "tools" / "ci" / "check_version_sync_with_commit.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(REAL_SCRIPT.read_text())
    pj = (tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
          / ".claude-plugin" / "plugin.json")
    pj.parent.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps({"name": "vibe-ic", "version": version}))
    mj = tmp_path / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    mj.parent.mkdir(parents=True, exist_ok=True)
    mj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": version}]}))
    # THE THIRD MANIFEST, at the REPO ROOT. `/plugin update` reads this one as
    # the version truth, and the script gained a check for it at 7e1aab3e1f —
    # a landing that did not update this fixture, so every case here began
    # failing on a manifest the fixture never staged. Staging it is not the
    # whole fix: see `test_a_desynced_root_manifest_is_refused` below, without
    # which this line would merely make the red go away.
    rmj = tmp_path / ".claude-plugin" / "marketplace.json"
    rmj.parent.mkdir(parents=True, exist_ok=True)
    rmj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": version}]}))
    return script


def _desync_root(tmp_path: Path, version: str) -> None:
    """Leave the two maintainer manifests alone and move ONLY the root one."""
    rmj = tmp_path / ".claude-plugin" / "marketplace.json"
    rmj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": version}]}))


def _run(script: Path, tmp_path: Path, msg: str):
    mf = tmp_path / "COMMIT_MSG.txt"
    mf.write_text(msg)
    return _pr.run(["bash", str(script), str(mf)],
                          capture_output=True, text=True)


# ── #422: historical markers must exempt BOTH version spellings ───────────

def test_from_v_prefixed_is_historical(tmp_path):
    # the issue's required fixture: 'from v1.2.3' while plugin is HIGHER
    r = _run(_stage(tmp_path), tmp_path, "capture: iter-5 from v1.2.3 absorbed\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_from_bare_version_is_historical(tmp_path):
    r = _run(_stage(tmp_path), tmp_path, "capture: results from 1.2.3 run\n")
    assert r.returncode == 0, r.stdout + r.stderr


def test_other_v_suffixed_markers_now_work(tmp_path):
    script = _stage(tmp_path)
    for subj in ("fix: fixes v1.2.3 regression\n",
                 "doc: unchanged since v1.2.3\n",
                 "feat: replaces v1.2.3 parser\n"):
        r = _run(script, tmp_path, subj)
        assert r.returncode == 0, subj + r.stdout + r.stderr


def test_was_marker_still_works(tmp_path):
    # the pre-fix workaround marker must keep working
    r = _run(_stage(tmp_path), tmp_path, "capture: iter-5 (was v1.2.3)\n")
    assert r.returncode == 0, r.stdout + r.stderr


# ── true-positive direction preserved ──────────────────────────────────────

def test_forward_claim_ahead_of_bump_still_blocks(tmp_path):
    r = _run(_stage(tmp_path), tmp_path, "feat(v1.2.3): new gate\n")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "claims v1.2.3" in r.stdout


def test_forward_claim_matching_bump_passes(tmp_path):
    r = _run(_stage(tmp_path, version="1.2.3"), tmp_path, "feat(v1.2.3): new gate\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_historical_subject_falls_through_to_body_claim(tmp_path):
    # subject's only mention is historical → body's forward claim governs
    msg = "capture: iter-5 from v1.2.3\n\nbump to v9.9.9 with new lessons\n"
    r = _run(_stage(tmp_path), tmp_path, msg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout and "9.9.9" in r.stdout


def test_no_version_in_message_skips(tmp_path):
    r = _run(_stage(tmp_path), tmp_path, "docs: clarify pad-ring viewing notes\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_flow_namespace_version_is_not_a_claim(tmp_path):
    # "flow v2.3.2" cites the canonical-flow DOC version (sibling
    # namespace) — mirrors the staged-diff guard's carve-out.
    script = _stage(tmp_path, "0.2.92")
    cp = _run(script, tmp_path,
              "mirror(docs): docs aligned to flow v2.3.2 step table\n")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "SKIP" in cp.stdout


def test_superseded_and_retire_markers_are_historical(tmp_path):
    script = _stage(tmp_path, "0.2.92")
    cp = _run(script, tmp_path,
              "docs: retire v2.2.0 docs (superseded by v2.3.2 set)\n")
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_flow_word_not_immediate_still_blocks(tmp_path):
    # strict immediacy: "the flow. v9.9.10 ships X" — period is not a
    # stripped separator, so this stays a forward plugin claim.
    script = _stage(tmp_path, "9.9.9")
    cp = _run(script, tmp_path, "feat: the flow. v9.9.10 ships X\n")
    assert cp.returncode == 1, cp.stdout + cp.stderr


def test_a_desynced_root_manifest_is_refused(tmp_path):
    """The root manifest is the one a USER resolves, so it must be checked.

    Before 7e1aab3e1f this script compared the commit message against the two
    manifests a MAINTAINER edits and nothing else. MEASURED at the time: set the
    root manifest to 9.9.9, leave the other two correct, and it printed
    `PASS: ... ↔ ... ↔ ...` and exited 0 — a user's `/plugin update` would then
    silently resolve the wrong version with no gate anywhere saying so.

    This case exists so that staging the third manifest in `_stage` cannot be
    mistaken for the fix. Staging alone makes the red go away; only this makes
    the check mean something.
    """
    script = _stage(tmp_path, "1.2.3")
    _desync_root(tmp_path, "9.9.9")
    cp = _run(script, tmp_path, "feat: something [v1.2.3]")
    assert cp.returncode == 1, (
        "a root-only desync was accepted; the manifest `/plugin update` reads "
        "is unchecked again\n" + cp.stdout + cp.stderr)
    assert "ROOT" in (cp.stdout + cp.stderr), (
        "it failed, but not for the root manifest — the message must say which "
        "of the three is wrong or the next reader edits the wrong file")


def test_an_absent_root_manifest_is_not_a_pass(tmp_path):
    """"I could not find the version" is not "the version is right"."""
    script = _stage(tmp_path, "1.2.3")
    (tmp_path / ".claude-plugin" / "marketplace.json").unlink()
    cp = _run(script, tmp_path, "feat: something [v1.2.3]")
    assert cp.returncode == 1, (
        "an absent root manifest passed; an unreadable version is not a "
        "matching one\n" + cp.stdout + cp.stderr)

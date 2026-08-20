#!/usr/bin/env python3
"""An image-anchor push is SCOPED to the gates that can assert something.

The anchor advance is `tools/vibeic-eda/VERSION` plus the live pointers
`sync_image_version.py --set` rewrites — a version STRING moving through a fixed
set of files, with no plugin logic in it. The expensive tier audits the plugin,
so on that diff it examines nothing; `--check` examines exactly the two ways an
anchor bump goes wrong (a half-rewrite, and an anchor moved backwards), so the
hook runs that in the stamp's place.

THE DISTINCTION IS THE WHOLE POINT. "These gates have no assertion power over
these paths" is a rule a machine can apply and a test can pin. "Anchor pushes are
trusted" is a habit. One extra path in the diff and the full tier runs again, so
code cannot ride in on an anchor — and every way the check itself can fail
resolves toward MORE gating, never less.

The scope block is executed here against stubs, not merely grepped: a rule
asserted only by string-matching passes on a file that kept the words and broke
the logic.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"
_SYNC = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"

_OWNED_SAMPLE = "tools/vibeic-eda/VERSION\nREADME.md\ndocs/INSTALL.md\n"


def _code_lines() -> str:
    return "\n".join(l for l in _HOOK.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


def _scope_block() -> str:
    """The ANCHOR_ONLY decision, lifted out of the hook verbatim."""
    src = _HOOK.read_text(encoding="utf-8")
    start = src.index("ANCHOR_ONLY=0")
    end = src.index("# --- the gates gatekeeper-ci.yml", start)
    return src[start:end]


def _decide(*, owned: str, changed: str, tool_rc: int = 0) -> int:
    """Run the real block with `python3` and `git diff` stubbed. Returns
    ANCHOR_ONLY."""
    # Heredocs, not `!r`: a Python repr embeds `\n` as two characters, and
    # `printf '%s'` inside bash single quotes keeps them literal — the stub
    # would hand the block one long path instead of a list, and every case
    # would "pass" by taking the full tier for the wrong reason.
    harness = f"""
set -u
REPO_ROOT=/nonexistent
PUSH_RANGE=range
PUSH_BASE=base
PUSH_TO_MAIN=1
python3() {{ cat <<'OWNED_EOF'
{owned}OWNED_EOF
return {tool_rc}; }}
git() {{ cat <<'CHANGED_EOF'
{changed}CHANGED_EOF
}}
{_scope_block()}
echo "ANCHOR_ONLY=$ANCHOR_ONLY"
"""
    out = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    m = re.search(r"ANCHOR_ONLY=(\d)", out.stdout)
    assert m, f"harness produced no verdict:\n{out.stdout}\n{out.stderr}"
    return int(m.group(1))


# ── the change: a real anchor push is scoped ────────────────────────────────

def test_version_plus_owned_pointers_is_an_anchor_push():
    assert _decide(owned=_OWNED_SAMPLE,
                   changed="tools/vibeic-eda/VERSION\nREADME.md\n") == 1


def test_version_alone_is_an_anchor_push():
    assert _decide(owned=_OWNED_SAMPLE, changed="tools/vibeic-eda/VERSION\n") == 1


# ── it cannot be used to smuggle anything ───────────────────────────────────

@pytest.mark.parametrize("extra", [
    "vibe-ic-marketplace/plugins/vibe-ic/programs/flow_orchestrate.py",
    "tools/git-hooks/pre-push",
    ".github/workflows/ci.yml",
    "benchmark-data/evaluation/x/report.json",
])
def test_one_path_outside_the_owned_set_takes_the_full_tier(extra):
    """LOAD-BEARING. If this ever returns 1, an anchor push is a way to land
    arbitrary code with the plugin audit skipped."""
    assert _decide(owned=_OWNED_SAMPLE,
                   changed=f"tools/vibeic-eda/VERSION\n{extra}\n") == 0


def test_a_push_that_does_not_touch_VERSION_is_not_an_anchor_push():
    """Rewriting the pointers WITHOUT moving VERSION is drift, not an anchor."""
    assert _decide(owned=_OWNED_SAMPLE, changed="README.md\ndocs/INSTALL.md\n") == 0


# ── every uncertainty resolves toward more gating ───────────────────────────

def test_an_unavailable_tool_takes_the_full_tier():
    assert _decide(owned="", changed="tools/vibeic-eda/VERSION\n", tool_rc=1) == 0


def test_an_unreadable_diff_takes_the_full_tier():
    assert _decide(owned=_OWNED_SAMPLE, changed="") == 0


# ── structure ───────────────────────────────────────────────────────────────

def test_the_owned_list_is_asked_for_not_copied_into_the_hook():
    """Two copies drift, and the direction it breaks in is a path `--set`
    rewrites that the hook does not recognise."""
    code = _code_lines()
    assert "--list-owned-paths" in code
    for owned in ("docs/INSTALL.md", "fault_atpg_run.py", "INSTALL_GUIDE.md"):
        assert owned not in code, (
            f"{owned} is hardcoded in the hook; it must come from "
            "--list-owned-paths")


def test_the_drift_check_replaces_the_stamp_rather_than_nothing():
    """A conditional whose scoped branch runs no gate at all is a skip wearing
    a conditional."""
    code = _code_lines()
    seg = code[code.index('if [ "$ANCHOR_ONLY" = "1" ]'):]
    seg = seg[:seg.index("gatekeeper-stamp")]
    assert "sync_image_version.py" in seg and "--check" in seg
    assert "FAILED=1" in seg, "the scoped branch must be able to fail the push"


def test_the_tool_really_lists_VERSION_first():
    """The hook requires `tools/vibeic-eda/VERSION` by name; if the tool stopped
    emitting it, every anchor push would silently take the full tier."""
    out = subprocess.run(["python3", str(_SYNC), "--list-owned-paths"],
                         capture_output=True, text=True, cwd=str(_REPO))
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0] == "tools/vibeic-eda/VERSION"

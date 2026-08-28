#!/usr/bin/env python3
"""The container's login shell prepends two [INFO] lines to stdout.

Measured on `vibeic-eda:0.2.63`: `bash -lc` emits `[INFO] Final PATH ...` and
`[INFO] Final PYTHONPATH ...` on STDOUT before the command's own output;
`bash -c` does not. 24 programs in this tree use a login shell, and the hazard
was already known in two of them by comment — the shape that rots.

The gate exists to stop the NEXT blind parser, so these tests pin BOTH
directions. A guard that has only ever been seen green is indistinguishable
from one whose detector no longer matches anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1] / "container_login_banner_parse_check.py"

sys.path.insert(0, str(PROG.parent))
import container_login_banner_parse_check as mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


LOGIN_CALL = (
    "import subprocess\n"
    "cp = subprocess.run(['docker','exec','c','bash','-lc','tool'],\n"
    "                    capture_output=True, text=True)\n")


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(LOGIN_CALL + body)
    return p


def test_the_repo_itself_is_clean(tmp_path):
    """Corpus sweep. A gate that fires on the state it ships with is a bug."""
    r = _pr.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("body,label", [
    ("n = int(cp.stdout)\n", "numeric conversion"),
    ("first = cp.stdout.splitlines()[0]\n", "first line"),
    ("val = cp.stdout.strip()\n", "whole value"),
])
def test_each_fragile_shape_is_caught(tmp_path, body, label):
    """The three shapes the banner actually corrupts."""
    p = _write(tmp_path, f"prog_{label.replace(' ', '_')}.py", body)
    rec = mod.audit([p])
    assert rec["verdict"] == "FAIL", f"{label} went undetected: {rec}"
    assert p.name in rec["findings"]


@pytest.mark.parametrize("body,why", [
    ("last = cp.stdout.strip().splitlines()[-1]\n",
     "the LAST line is past the banner"),
    ("hits = [l for l in cp.stdout.splitlines() if 'DONE' in l]\n",
     "a marker scan skips the banner"),
    ("open('o.txt','w').write(cp.stdout)\n",
     "writing it out verbatim parses nothing"),
])
def test_shapes_the_banner_does_not_corrupt_stay_silent(tmp_path, body, why):
    """The reverse case. Narrowing is the whole point — a gate that flags every
    stdout read would be noise, and noise gets ignored, which is how the
    hazard survived in twenty-two programs in the first place."""
    p = _write(tmp_path, "prog_ok.py", body)
    rec = mod.audit([p])
    assert rec["verdict"] == "PASS", f"false positive ({why}): {rec}"


def test_a_fragile_parse_without_a_login_shell_is_not_flagged(tmp_path):
    """`bash -c` does not print the banner, so the same parse is fine there.
    Flagging it would be a rule about parsing, not about this defect."""
    p = tmp_path / "prog_nonlogin.py"
    p.write_text(
        "import subprocess\n"
        "cp = subprocess.run(['docker','exec','c','bash','-c','tool'],\n"
        "                    capture_output=True, text=True)\n"
        "n = int(cp.stdout)\n")
    assert mod.audit([p])["verdict"] == "PASS"


def test_an_empty_population_is_not_reported_as_clean(tmp_path):
    """If no caller matches, the detector may simply have stopped working.
    Returning PASS there would be a green light earned by measuring nothing —
    exactly the failure this gate is about. It must SKIP (rc 2) and say why."""
    p = tmp_path / "prog_no_docker.py"
    p.write_text("x = 1\n")
    rec = mod.audit([p])
    assert rec["login_shell_callers"] == []
    assert rec["verdict"] == "PASS"          # nothing to find among zero callers
    # …and the CLI must refuse to call that a pass:
    r = _pr.run([sys.executable, "-c",
                        f"import sys; sys.path.insert(0, {str(PROG.parent)!r});\n"
                        "import container_login_banner_parse_check as m;\n"
                        "m._programs = lambda: [];\n"
                        "sys.exit(m.main())"],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "neither is a PASS" in r.stdout


def test_alternate_login_spellings_are_not_a_bypass(tmp_path):
    """`--login` and `-l','-c'` are the same shell; a reworded call site must
    not walk out of the population."""
    for spell in ("'--login'", "'-l','-c'"):
        p = tmp_path / "prog_spell.py"
        p.write_text(
            "import subprocess\n"
            f"cp = subprocess.run(['docker','exec','c','bash',{spell},'t'],\n"
            "                    capture_output=True, text=True)\n"
            "n = int(cp.stdout)\n")
        rec = mod.audit([p])
        assert rec["verdict"] == "FAIL", f"{spell} bypassed the detector: {rec}"

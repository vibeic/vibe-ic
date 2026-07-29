#!/usr/bin/env python3
"""The flow must run OUR klayout, and both halves of that are load bearing.

vibeic-eda#17. The fork patches the LEF/DEF importer to honour tech-LEF
MANUFACTURINGGRID. Measured on the fork's own fixture — same DEF, same tech
LEF, 5 nm grid:

    base pymod                          OFFGRID_VERTICES_TOTAL = 8
    fork pymod                          OFFGRID_VERTICES_TOTAL = 0
    fork pymod + base LD_LIBRARY_PATH   OFFGRID_VERTICES_TOTAL = 8   <-- the trap

The last line is why these tests exist. The pymod extension modules link
libklayout_db.so by SONAME, so pointing sys.path at our build while the base
directory is on the library search path reproduces the base's behaviour exactly.
A fix that moved only sys.path would look right and change nothing.

These drive the real fragments — the shell one through a real shell, the Python
one through a real interpreter — rather than asserting that the source contains
a string.
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P                            # noqa: E402


def _run_preamble(tmp_path, dirs):
    """Execute the real shell fragment against a fabricated /foss/tools."""
    root = tmp_path / "foss" / "tools"
    for d in dirs:
        (root / d).mkdir(parents=True)
        exe = root / d / "klayout"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    frag = P.KLAYOUT_PREFER_FORK_SH.replace("/foss/tools/", f"{root}/")
    out = subprocess.run(
        ["bash", "-c", frag + 'echo "$PATH|$LD_LIBRARY_PATH|$KLAYOUT_PYMOD"'],
        capture_output=True, text=True, env={**os.environ, "LD_LIBRARY_PATH": ""})
    path, ldp, pymod = out.stdout.strip().split("|")
    return path.split(":")[0], ldp.split(":")[0], pymod


def test_the_fork_wins_when_the_image_has_one(tmp_path):
    first_path, first_lib, pymod = _run_preamble(
        tmp_path, ["klayout", "klayout-vibeic"])
    assert first_path.endswith("klayout-vibeic")
    assert first_lib.endswith("klayout-vibeic"), \
        "PATH alone is not enough — the libraries decide the geometry"
    assert pymod.endswith("klayout-vibeic/pymod")


def test_the_base_is_used_when_there_is_no_fork(tmp_path):
    """A stock iic-osic-tools image must still work."""
    first_path, first_lib, pymod = _run_preamble(tmp_path, ["klayout"])
    assert first_path.endswith("/klayout")
    assert first_lib.endswith("/klayout")
    assert pymod.endswith("/klayout/pymod")


def test_the_python_half_follows_the_shell_half(tmp_path):
    """One resolution, not two: a binary and its libraries from one build.

    The Python fragment reads what the shell already chose. Two independent
    resolutions is how you end up running our binary against the base's
    libraries — which measures as the base.
    """
    chosen = tmp_path / "chosen-pymod"
    chosen.mkdir()
    out = subprocess.run(
        [sys.executable, "-c", P.KLAYOUT_PYMOD_PY + "print(sys.path[0])"],
        capture_output=True, text=True,
        env={**os.environ, "KLAYOUT_PYMOD": str(chosen)})
    assert out.stdout.strip() == str(chosen), out.stderr[-300:]


def test_the_python_half_still_resolves_with_no_shell_hint():
    """Fall back rather than crash when the fragment is used on its own."""
    out = subprocess.run(
        [sys.executable, "-c", P.KLAYOUT_PYMOD_PY + "print('ok')"],
        capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "KLAYOUT_PYMOD"})
    assert out.returncode == 0 and "ok" in out.stdout


def test_no_call_site_hard_codes_the_base_klayout():
    """WIRING, which is where a fix like this leaks.

    Stated limit: this reads the call sites rather than executing them — the
    real ones need a container and a GDS. It can only catch a site that names
    the base tree directly, which is exactly how both of the sites this issue
    found were written.

    A string that names the base tree AND the fork tree is a resolver, and the
    base path in it is the fallback that keeps a stock image working. A string
    that names only the base is a hard-code. That distinction is the property,
    not a carve-out for the two constants — a resolver written tomorrow passes,
    and a hard-code hidden inside one does not.
    """
    src = pathlib.Path(P.__file__).read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            names_base = ("/foss/tools/klayout/" in v
                          or v.endswith("/foss/tools/klayout"))
            if names_base and "klayout-vibeic" not in v:
                offenders.append((node.lineno, v[:70]))
    assert not offenders, (
        "these name the BASE klayout tree directly, so the fork never runs "
        "there: " + "; ".join(f"line {l}: {v}" for l, v in offenders))

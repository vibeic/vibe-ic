# BACKLOG-v13 Wave 6 (v0.119.38). pytest discovery fix:
#
# When pytest is invoked from the marketplace root
# (`cd vibe-ic-marketplace && pytest -q`) the plugin's own
# pytest.ini is no longer the configfile, so the implicit
# rootdir-on-path behaviour that lets
#
#   from programs.host_soft_reset_unwake_path_check import main
#
# resolve in plugins/vibe-ic-d/tests/* no longer applies. This
# conftest.py prepends the plugin's `programs/` directory to
# sys.path during pytest collection so those imports keep working
# regardless of which CWD pytest was launched from.
#
# This file is a no-op for plugins/vibe-ic-d/programs/tests/*, which
# import via `from <module> import ...` — it just adds the same
# directory to sys.path, which is harmless.
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE / "programs"
if _PROGRAMS.is_dir() and str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
# Also expose the plugin root so `from programs.foo import bar` works.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ORGANIC #574 — robust waveform-artifact hygiene. Many tests run `vvp` on an
# official benchmark testbench that carries `$dumpfile("wave.vcd")`; when such a
# vvp runs with cwd inherited (the plugin tree under pytest) it leaves a stray
# wave.vcd that the waveform-hygiene gate (test_v0_3_38) flags — and whether it
# flags depends on TEST ORDER (a leaker after the gate passes that run, a leaker
# before it FAILs). Root-cause fixes pin the known leakers to cwd=tempdir; this
# autouse fixture is the order-independent safety net: after EVERY test it removes
# any stray waveform dump from the 3 spots vvp can land one (the test's cwd, the
# plugin root, programs/). Cheap (a few unlink calls), general (catches any future
# leaker too), and never touches a committed file (all such dumps are gitignored).
_WAVE_SUFFIXES = (".vcd", ".fst", ".ghw", ".shm")


@pytest.fixture(autouse=True)
def _strip_stray_waveform_artifacts():
    yield
    spots = {_HERE, _PROGRAMS}
    try:
        spots.add(Path.cwd())
    except OSError:
        pass
    for spot in spots:
        try:
            for f in spot.iterdir():
                if f.is_file() and f.suffix in _WAVE_SUFFIXES:
                    f.unlink(missing_ok=True)
        except (OSError, FileNotFoundError):
            pass

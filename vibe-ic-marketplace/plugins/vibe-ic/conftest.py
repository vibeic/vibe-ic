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

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE / "programs"
if _PROGRAMS.is_dir() and str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
# Also expose the plugin root so `from programs.foo import bar` works.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

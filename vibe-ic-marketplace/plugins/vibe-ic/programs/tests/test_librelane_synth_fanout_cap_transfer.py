"""The Librelane Step-9 caller transfers a declared cap into ABC's normal API."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as runner  # noqa: E402


class LibrelaneSynthFanoutTransfer(unittest.TestCase):


    def test_pinned_librelane_api_emits_exact_cap_without_sizing(self):
        from librelane.scripts.pyosys.construct_abc_script import ABCScriptCreator

        config = {
            "CLOCK_PERIOD": 24,
            "SYNTH_ABC_LEGACY_REFACTOR": False,
            "SYNTH_ABC_LEGACY_REWRITE": False,
            "SYNTH_ABC_USE_MFS3": False,
            "SYNTH_ABC_AREA_USE_NF": False,
            "MAX_FANOUT_CONSTRAINT": 4,
            "MAX_TRANSITION_CONSTRAINT": None,
            "SYNTH_ABC_BUFFERING": False,
            "SYNTH_ABC_BUFFER_ONLY": True,
            "SYNTH_SIZING": False,
        }
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            path = Path(ABCScriptCreator(config).generate_abc_script(
                temp, "AREA 0"))
            script = path.read_text()
        self.assertEqual(script.count("buffer -N 4"), 1)
        self.assertNotIn("upsize", script)
        self.assertNotIn("dnsize", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A Phase-3 window dispatches one real runner site without disturbing inputs."""
import subprocess
import sys
from pathlib import Path

import phase3_one_shot_runner as p3







def test_real_runner_cli_exposes_window():
    proc = subprocess.run([sys.executable, str(Path(p3.__file__)), "--help"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--entry-step" in proc.stdout and "--exit-step" in proc.stdout

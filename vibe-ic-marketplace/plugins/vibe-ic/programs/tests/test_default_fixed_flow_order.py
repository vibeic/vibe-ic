"""Cold/resume Default order controls. Synthetic transport is not IC proof."""
import json
from pathlib import Path

import pytest


















def test_pinned_native_stream_recipe_accepts_the_recorded_cli_flags():
    import subprocess
    import sys
    from librelane.common import get_script_dir
    recipe = Path(get_script_dir()) / 'klayout/stream_out.py'
    result = subprocess.run([sys.executable, str(recipe), '--help'],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    for flag in ('--input-lef', '--output', '--top', '--lyp', '--lyt', '--lym', '--with-gds-file'):
        assert flag in result.stdout, (flag, result.stdout)

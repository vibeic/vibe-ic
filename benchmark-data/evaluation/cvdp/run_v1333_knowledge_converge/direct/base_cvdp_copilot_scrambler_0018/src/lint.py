import subprocess

# ----------------------------------------
# - Simulate
# ----------------------------------------

def test_lint():
    cmd = "verilator --lint-only -Wall -Wno-EOFNEWLINE /src/lint_config.vlt $VERILOG_SOURCES > lint_results.log 2>&1"
    assert subprocess.run(cmd, shell=True).returncode == 0, "Linting return errors."
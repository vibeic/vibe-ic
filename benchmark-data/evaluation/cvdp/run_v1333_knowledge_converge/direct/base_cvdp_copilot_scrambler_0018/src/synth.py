import os
import re
import subprocess

# ----------------------------------------
# - Simulate
# ----------------------------------------

def synth():
    cmd = "yosys -s /code/scripts/synth.tcl -l /code/rundir/synth.log"
    return subprocess.run(cmd, shell=True).returncode

def parse_yosys_log(log_path):

    """Extract the relevant statistics from a Yosys log file and check for errors."""

    stats = {}
    has_error = False
    with open(log_path, 'r') as file:
        for line in file:
            if "error" in line.lower():
                has_error = True
            if any(key in line for key in ["Number of cells", "Number of wires", 
                                            "Number of wire bits", "Number of memories", 
                                            "Number of memory bits", "Number of processes"]):
                match = re.search(r'^\s+(Number of \w+):\s+(\d+)', line)
                if match:
                    stats[match.group(1)] = int(match.group(2))

    return stats, has_error

def test_yosys():

    # CHeck for logs
    log_file = "/code/rundir/synth.log"

    if os.path.exists(log_file):
        error = os.remove(log_file)

    # Check if synthesis doesn't report any errors through returncode
    assert(error == 0), "Synthesis execution returned error."

    # Run synthesis
    synth()

    # Compare statistics from two Yosys logs and determine if synthesis improved or failed.
    stats_after, error_after = parse_yosys_log(log_file)

    print("\nYosys Synthesis Log Comparison:")
    print(stats_after)
    print(error_after)

    if os.environ.get("ERROR") is not None:
        print("Improvement detected: Errors found in the before log but none in the after log. RTL is now synthesizable.")
        return True
    if error_after:
        print("No upgrades in synthesis: Errors detected in the after log. Synthesis failed.")
        return False

    improvs = os.environ.get("IMPROVEMENTS")
    improvs = improvs.split(" ")

    # Compare relevant statistics
    improvement_found = False

    for key in improvs:

        up_key = str(key).upper()
        value_before = int(os.environ.get(up_key))
        value_after  = stats_after[f"Number of {key}"]

        difference = value_after - value_before
        if difference < 0:
            improvement_found = True
            print(f"{key}: {value_before} -> {value_after} (Improved by {abs(difference)})")
        else:
            print(f"{key}: {value_before} -> {value_after} (No improvement)")

    assert(improvement_found), "Optimization failed: No improvements found in the log file."
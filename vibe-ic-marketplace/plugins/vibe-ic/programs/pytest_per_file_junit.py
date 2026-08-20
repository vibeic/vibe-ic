import os, sys, time, pathlib
arm = os.environ.get('GATEKEEPER_VERIFY_ARM', '?')
junit = sys.argv[sys.argv.index('--junit') + 1]
probe = os.environ.get('ARM_PROBE_DIR')
start = time.time()
time.sleep(float(os.environ.get('ARM_DWELL', '0')))
if probe:
    pathlib.Path(probe, arm).write_text(f'{start} {time.time()}\n')
pathlib.Path(junit).write_text(
    os.environ['CAND_JUNIT_TEXT'] if arm == 'B1'
    else os.environ['BASE_JUNIT_TEXT'])
print('=== pytest junit summary')
print('AGGREGATE_COMPLETE rc=0')

# Explicit D13 captured-input readset controls

These readonly external-carrier controls are explicitly selected, never default
test discovery. Set VIBEIC_D13_READSET_PROGRAMS to the frozen programs directory
and VIBEIC_D13_READSET_INPUT to the CONTROL_INPUT.json descriptor, then run:

```bash
python3 -B -m pytest -q -p no:cacheprovider \
  "$VIBEIC_D13_READSET_PROGRAMS/tests/fixtures/d13_retained_input_readset_control.py"
```

The TEST_ONLY historical input lookup models restoring the actual original
source.json bytes and storing the post-run adopted payload at its own normal
source_reference location. It never changes live carrier bytes or any approval.
All project authority is consumed unchanged; no authority hook grants adoption.
These controls execute readers only, not simulation, coverage or qualification.

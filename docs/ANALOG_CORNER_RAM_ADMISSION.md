# Analog PVT corner RAM admission

The canonical A4 producer is `programs/analog_real_corner_sweep.py`, reached
from `programs/analog_one_shot_runner.py`.  Its independently launched PVT
corners use `programs/analog_corner_admission.py`; do not add a side launcher
that A4 does not call.

Set a non-zero per-corner reservation before a parallel sweep:

```bash
export VIBEIC_ANALOG_CORNER_MEMORY=32GiB
export VIBEIC_ANALOG_CORNER_HEADROOM=16GiB
```

The scheduler uses physical RAM only: `physical RAM - headroom - active
labelled corner reservations - durable local reservations`.  Swap is never
allocatable.  It refuses a missing, zero, malformed, or over-budget declaration
before `docker run`.  For 126 GiB RAM, a 16 GiB headroom and 32 GiB reservations,
the safe concurrency is three; a fourth corner waits for/requires a released
reservation rather than raising the host commitment to 128 GiB.

Every launched corner keeps the declared `--memory` and matching
`--memory-swap` limit, `--init`, image, working directory, mount and complete
simulation argument vector.  Admission records are durable JSON Lines under
`reports/analog/corner-admission/`: `plans.jsonl`, `reservations.jsonl`, and
`completions.jsonl`, with current state in `reservations.json`.

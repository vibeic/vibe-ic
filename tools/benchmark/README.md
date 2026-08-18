# Benchmark regression suite — BACKLOG-v10 P2.2 + v11 P2.2

Pin a frozen project tree under `<name>_golden/project/` plus a one-line
`expected.txt` (`PASS`, `PASS_WITH_WAIVERS`, or `FAIL`). The runner
asserts that `flow_compliance_check.py` still produces the pinned
verdict on every plugin commit.

## Layout

```
tools/benchmark/
  README.md
  run_benchmark.sh
  <project>_golden/
    project/                 # frozen project tree (RTL + docs + waivers)
    expected.txt             # PASS | PASS_WITH_WAIVERS | FAIL (one line)
    NOTES.md                 # (optional) why this golden state
```

## Usage

```bash
tools/benchmark/run_benchmark.sh
```

Exit 0 = every golden's verdict matches; exit 1 = at least one
diverged; exit 2 = setup error / no goldens found.

## Adding a benchmark

1. Copy a frozen project tree (RTL + generated_docs + waivers.json) to
   `tools/benchmark/<name>_golden/project/`.
2. Run flow_compliance_check on it, capture the `Overall:` verdict, and
   write that token to `tools/benchmark/<name>_golden/expected.txt`.
3. Commit. CI will now alert if the verdict drifts on any subsequent
   plugin change.

## When the runner fails

Either the plugin regressed (debug the gate that flipped) or the
expected verdict needs updating (intentional behaviour change — bump
the pinned verdict + add a NOTES.md row explaining why).

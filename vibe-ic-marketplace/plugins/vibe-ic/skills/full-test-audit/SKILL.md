---
name: full-test-audit
description: "Run the requested test population and inspect actual tool coverage, native results, and remaining judgment without adding policy gates."
---

# Full test audit

Read `CHARTER.md`. A full test request concerns the actual current test
population and product behavior. Report the exact commands, environment,
collected tests, executed tests, failures, skips, and measurement gaps.

## Run the current tests

Use the repository's `run_tests.sh` test-directory discovery and inspect its
current invocation before running it. The configured bare pytest collection
and other test directories must be distinguished in the result.

```bash
cd <plugin>
./run_tests.sh --list-tiers
python3 -m pytest --collect-only
./run_tests.sh
```

Use the owner's resource limits and temporary directory. An import error or an
unavailable native dependency is an environment or collection problem to
resolve or disclose. It is not a passing test. Compare failure identities and
outcomes with the appropriate control revision when the task asks for parity.

## Inspect product coverage

If the request uses the older D1, D2, or D3 labels, explain their actual scope.
For D1, identify behavior with no meaningful test coverage. For D2, identify
selected native tools that did not run or left no report. For D3, identify the
judgment still required to interpret or fix the tool result. These labels do
not require one checker per program or per step.

Run the public entry when unit tests cannot establish the changed behavior.
For each measured step, read the native report and compare the number with its
original limit. Review what the tool left unmeasured. Do not replace native
execution with report lint, file-presence assertions, or another policy layer.

For benchmarks, preserve Program First, independent blind AI review and backup,
clean-room actors, and official scoring. For analog, mixed-signal, and FPGA
work, retain the native tool and hardware evidence appropriate to the request.
Keep run outputs outside the plugin repository and leave landing to the
owner's currently authorized workflow.

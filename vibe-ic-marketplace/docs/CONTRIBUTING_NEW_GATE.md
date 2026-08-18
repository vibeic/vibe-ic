# Contributing — NEW_GATE

This is a focused per-topic guide. For the umbrella partner-plugin layout
+ submission workflow, see [`CONTRIBUTING_PARTNER_PLUGIN.md`](./CONTRIBUTING_PARTNER_PLUGIN.md).

## What you ship

```
programs/<gate_name>_check.py
tests/test_<gate_name>_check.py
```

## Gate contract

- argparse `<project_dir>`
- exit 0 PASS / SKIP / WAIVED-WITH-WAIVER, 1 FAIL, 2 IO error
- print verdict + 1-line reason on stdout
- when applicable, write JSON detail to `reports/gates/<gate_name>.json`

## Wire into the flow

Edit `plugins/vibe-ic/flow/phase2_phase3.yaml` (or relevant phase YAML) to add your gate to the appropriate step's `gate.all_of` list. Use:

```yaml
- program_exit_zero: "<gate_name> . --json reports/gates/<gate_name>.json"
```

## chip-AGNOSTIC requirement

Your gate MUST silent-skip when its preconditions aren't met (e.g. project doesn't have the input doc your gate validates). NEVER FAIL on a project that legitimately doesn't apply to your gate's domain. Use `ic_class_profile.py` if you need class-aware applicability.

## Waiver semantics

If your gate is non-fatal in some legitimate cases, define a waiver key (`<gate>_intentional` ≥40 chars). Document in your gate's docstring.

## Tests

Ship pytest cases for both PASS and FAIL paths under `plugins/vibe-ic/programs/tests/`. Reference: `plugins/vibe-ic/programs/tests/test_*.py`.

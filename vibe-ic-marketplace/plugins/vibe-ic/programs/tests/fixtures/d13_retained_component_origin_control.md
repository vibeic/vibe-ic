# Explicit retained D13 native-origin control

This control requires an external real carrier and an inert execution proposal.
It is deliberately not named `test_*.py`; normal checkout discovery must not
acquire this private carrier dependency. The TEST_ONLY adoption-authority hook
never writes actual adoption or grants canonical row credit.

Explicit invocation (only when this real-carrier control is requested):

```bash
VIBEIC_D13_COMPONENT_PROGRAMS="$PROGRAMS" \
VIBEIC_D13_COMPONENT_PROPOSAL="$UNADOPTED_SOURCE_EXECUTION_PROPOSAL" \
python3 -B -m pytest -q -p no:cacheprovider \
  "$PROGRAMS/tests/fixtures/d13_retained_component_origin_control.py"
```

Mount the declared source, carrier, original source tree and referenced native
host evidence read-only inside the pinned image. Use an exclusive output path
and the existing 2CPU/4GiB equal-swap/networknone launch. A collection-only check
uses `--collect-only` and does not execute fixtures or read the proposal.

Path-only receipt mapping:

- Previous: `tests/test_d13_retained_component_origin.py`
- Current: `tests/fixtures/d13_retained_component_origin_control.py`
- Module/test AST and file bytes are identical. Reuse the sealed seven-control
  execution receipt under `D13-retained-component-consumer/final-controls/head`;
  only the collection path/module prefix changes. No native control replay.

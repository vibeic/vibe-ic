# Issue #2236 follow-up receipt

**Base:** `12603a530833c42484eb93e5a3623ff5d9b01218`  
**Implementation head:** `c6576925a83279712507719dad4c8f2e70037d04`

## Delivered

The host-scoped, `flock`-protected ledger reconciles a live labelled Docker
container with its durable `vibeic.corner.token` reservation exactly once.  A
larger live declaration remains conservatively charged, as do unmatched and
legacy containers.  Missing Docker label values (`<no value>`) are individual
legacy containers, not a shared token.  The launch path retains `--init`,
equal `--memory`/`--memory-swap`, and never uses `docker exec`.

The deterministic regression invokes the real Docker-discovery adapter through
a fake Docker runner.  With 126 GiB RAM, 16 GiB headroom, and live labelled
32 GiB containers matching ledger tokens, it admits exactly three corners,
accounts for 96 GiB, and refuses the fourth.  A companion case confirms two
unlabelled live containers cannot collapse into one accounting entry.

## Evidence

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider \
  vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_issue2236_aggregate_ram_admission.py
23 passed

python3 -m py_compile vibe-ic-marketplace/plugins/vibe-ic/programs/analog_corner_admission.py
git diff --check
```

## Remaining limitations

Docker discovery errors, malformed reservations, and unreadable ledger state
refuse admission.  A stale durable reservation after a launcher crash remains
charged until an explicit release/recovery procedure; this is intentional
fail-closed behavior.  The deterministic test models Docker responses and does
not start, stop, or inspect any live analog workload.

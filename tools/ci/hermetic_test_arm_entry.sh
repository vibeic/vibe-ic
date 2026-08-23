#!/usr/bin/env bash
# BASE-owned direct PID1 entry for hermetic A1/B1 aggregate test arms.
set -euo pipefail

[ "${GATEKEEPER_RUNTIME_ROOT:-}" = "/runtime" ] \
  || { echo '[NORECORD] hermetic test arm has no trusted runtime root' >&2; exit 2; }
case "${GATEKEEPER_VERIFY_ARM:-}" in
  A1|B1) ;;
  *) echo '[NORECORD] hermetic test arm identity is not A1/B1' >&2; exit 2 ;;
esac
[ "${VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY:-}" = "1" ] \
  || { echo '[NORECORD] trusted pytest entry is not required' >&2; exit 2; }
[ "$#" -eq 0 ] \
  || { echo '[NORECORD] hermetic test arm accepts no subject arguments' >&2; exit 2; }
grace=${VIBEIC_PYTEST_SEMANTIC_STALL_GRACE:-}
if [ "$grace" != 600 ]; then
  echo '[NORECORD] hermetic test arm semantic stall grace differs from protected runtime' >&2
  exit 2
fi

PROGRAMS="/runtime/vibe-ic-marketplace/plugins/vibe-ic/programs"
cd /subject/vibe-ic-marketplace/plugins/vibe-ic \
  || { echo '[NORECORD] hermetic subject has no plugin root' >&2; exit 2; }
exec python3 -I -c \
  'import pathlib,runpy,sys; p=pathlib.Path(sys.argv[1]); sys.argv=sys.argv[1:]; sys.path.insert(0,str(p.parent)); runpy.run_path(str(p),run_name="__main__")' \
  "$PROGRAMS/pytest_per_file_junit.py" \
  --selection /input/selection \
  --junit /evidence/pytest.xml \
  --stall-after "$grace" \
  --aggregate-check \
  --aggregate-only \
  --aggregate-stall-after "$grace" \
  --hermetic-progress \
  -- python3 -I "$PROGRAMS/trusted_pytest_entry.py" \
  -o tmp_path_retention_policy=failed \
  -q -p no:cacheprovider

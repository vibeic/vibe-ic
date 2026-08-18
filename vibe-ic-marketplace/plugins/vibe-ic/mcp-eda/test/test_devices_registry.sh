#!/bin/bash
# test_devices_registry.sh — smoke test for the v0.67+ device plugin framework.
#
# Verifies (without real hardware, unless noted):
#   1. _registry.js + index.js parse without syntax errors
#   2. every src/devices/<category>/<vendor>/manifest.json is valid JSON
#   3. every manifest.tools[].driver exists and is executable
#   4. every driver responds to --help without crashing
#   5. every driver tolerates an empty-args invocation: produces a JSON
#      error body, never a Python traceback to stdout
#   6. v0.67 error taxonomy smoke:
#      - driver with bad JSON args produces error_code=invalid_argument
#      - keysight driver with phantom VID/PID produces
#        error_code=device_not_found
#      - error bodies ALWAYS have all 5 fields:
#        success / error_code / error / recoverable / last_seen_output
#   7. v0.67 validateManifest() rule coverage (mode/platform/timeout_ms)
#   8. v0.68 resources[] schema + URI convention + driver-side parseable
#      JSON for each declared resource's tool_mode; plus a fake-server
#      harness that proves registerDevices() invokes server.resource().
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEVICES_DIR="$ROOT_DIR/src/devices"

PASS=0
FAIL=0
TOTAL=0

ok() { echo "  PASS: $1"; PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); }
no() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); }

echo "========================================="
echo "  v0.67 device registry smoke test"
echo "========================================="

# 1. JS syntax
echo ""
echo "--- 1. JS syntax (node --check) ---"
if node --check "$DEVICES_DIR/_registry.js" 2>/dev/null; then
  ok "_registry.js parses"
else
  no "_registry.js fails node --check"
fi
if node --check "$ROOT_DIR/src/index.js" 2>/dev/null; then
  ok "index.js parses"
else
  no "index.js fails node --check"
fi

# 1b. Shared errors module importable
echo ""
echo "--- 1b. _shared/errors.py importable ---"
if python3 -c "
import sys
sys.path.insert(0, '$DEVICES_DIR/_shared')
from errors import (DeviceError, DeviceNotFoundError, PermissionError_,
                    DeviceTimeoutError, DeviceProtocolError,
                    VendorToolNotFoundError, DeviceBusyError,
                    InvalidArgumentError, EXIT_FOR_CODE)
assert EXIT_FOR_CODE['invalid_argument'] == 2
assert EXIT_FOR_CODE['device_not_found'] == 2
assert EXIT_FOR_CODE['timeout'] == 1
body = DeviceNotFoundError('x').as_json_body()
for k in ('success', 'error_code', 'error', 'recoverable', 'last_seen_output'):
    assert k in body, f'missing key {k}'
" 2>/dev/null; then
  ok "_shared/errors.py imports + EXIT_FOR_CODE complete + 5-field body shape"
else
  no "_shared/errors.py import or contract failed"
fi

# 2-5. Per-vendor checks
echo ""
echo "--- 2-5. Per-vendor manifest + driver checks ---"
shopt -s nullglob
# v0.66: two-level layout → glob <category>/<vendor-device>/manifest.json
for manifest in "$DEVICES_DIR"/*/*/manifest.json; do
  vendor_dir="$(dirname "$manifest")"
  vendor_name="$(basename "$vendor_dir")"
  category_name="$(basename "$(dirname "$vendor_dir")")"
  echo ""
  echo "[$category_name / $vendor_name]"

  # 2. JSON valid
  if python3 -c "import json,sys; json.load(open('$manifest'))" 2>/dev/null; then
    ok "$vendor_name/manifest.json is valid JSON"
  else
    no "$vendor_name/manifest.json is INVALID JSON"
    continue
  fi

  # Pull declared drivers (unique paths)
  drivers=$(python3 -c "
import json
m = json.load(open('$manifest'))
seen = []
for t in m.get('tools', []):
    d = t.get('driver')
    if d and d not in seen:
        seen.append(d)
        print(d)
")
  if [ -z "$drivers" ]; then
    no "$vendor_name has no driver paths"
    continue
  fi

  for d in $drivers; do
    drv="$vendor_dir/$d"
    # 3. Exists + executable
    if [ -f "$drv" ] && [ -x "$drv" ]; then
      ok "$vendor_name/$d exists and is executable"
    else
      no "$vendor_name/$d missing or not executable"
      continue
    fi

    # 4. --help works
    if "$drv" --help >/dev/null 2>&1; then
      ok "$vendor_name/$d --help exits 0"
    else
      no "$vendor_name/$d --help failed"
    fi

    # 5. Per-tool_mode empty-args invocation must produce parseable JSON.
    # v0.67: manifest's `mode` now means hw/sim/mock; driver dispatch
    # keyword is `tool_mode`. Fall back to `mode` for pre-v0.67
    # manifests, but in this repo there are none (hard rename).
    tool_modes=$(python3 -c "
import json
m = json.load(open('$manifest'))
seen = []
for t in m.get('tools', []):
    if t.get('driver') == '$d':
        mode = t.get('tool_mode') or ''
        if mode and mode not in seen:
            seen.append(mode)
            print(mode)
")
    # Per-mode timeout budget. v0.75: capture/pulse_check on a connected
    # scope wait for a trigger (default trigger_timeout_s=30 in
    # mode_capture). The smoke test's old 10s budget killed the driver
    # mid-poll → JSON never reached stdout. Bump to 35s for the
    # trigger-armed modes so the driver gets to emit its structured
    # DeviceTimeoutError JSON. Other modes still run with the snappier
    # 10s budget.
    _smoke_budget() {
      case "$1" in
        capture|pulse_check) echo 35 ;;
        *)                   echo 10 ;;
      esac
    }
    if [ -z "$tool_modes" ]; then
      # No modes declared — invoke without --mode
      out=$(echo '{}' | timeout 10 "$drv" --json-args - 2>/dev/null || true)
      if echo "$out" | python3 -c "import json,sys; json.loads(sys.stdin.read())" >/dev/null 2>&1; then
        ok "$vendor_name/$d (no-mode) emits JSON on empty args"
      else
        no "$vendor_name/$d (no-mode) did NOT emit JSON on empty args (got: $(echo "$out" | head -c 120))"
      fi
    else
      for mode in $tool_modes; do
        budget=$(_smoke_budget "$mode")
        out=$(echo '{}' | timeout "$budget" "$drv" --mode "$mode" --json-args - 2>/dev/null || true)
        if echo "$out" | python3 -c "import json,sys; json.loads(sys.stdin.read())" >/dev/null 2>&1; then
          ok "$vendor_name/$d --mode $mode emits JSON on empty args"
        else
          no "$vendor_name/$d --mode $mode did NOT emit JSON (got: $(echo "$out" | head -c 120))"
        fi
      done
    fi
  done
done

# 6. v0.67 error-taxonomy smoke checks (driver-agnostic behaviour guarantees).
#
# Checks applied to EACH driver:
#   (a) malformed JSON stdin → error_code == "invalid_argument"
#   (b) the returned JSON body has ALL FIVE canonical fields
#
# Checks applied to keysight-scope only (where we can control VID/PID):
#   (c) phantom VID/PID → error_code == "device_not_found"
#
# The 5-field contract is stronger than checking any specific code: it
# guarantees MCP clients can branch on `error_code` / `recoverable`
# without fearing missing keys.
echo ""
echo "--- 6. Error-taxonomy smoke (v0.67) ---"

_check_five_fields() {
  # Usage: _check_five_fields "<json-body>" "<label>"
  local body="$1"
  local label="$2"
  python3 - <<PY
import json, sys
try:
    b = json.loads('''$body''')
except Exception as e:
    print(f"NOT-JSON: {e}"); sys.exit(1)
for k in ("success", "error_code", "error", "recoverable", "last_seen_output"):
    if k not in b:
        print(f"MISSING: {k}"); sys.exit(2)
print("OK")
PY
}

for manifest in "$DEVICES_DIR"/*/*/manifest.json; do
  vendor_dir="$(dirname "$manifest")"
  vendor_name="$(basename "$vendor_dir")"
  drv="$vendor_dir/driver.py"
  if [ ! -x "$drv" ]; then continue; fi

  # Pick the first tool_mode to drive --mode with.
  first_mode=$(python3 -c "
import json
m = json.load(open('$manifest'))
for t in m.get('tools', []):
    if t.get('tool_mode'):
        print(t['tool_mode']); break
")

  # (a) malformed JSON → invalid_argument
  if [ -n "$first_mode" ]; then
    body=$(echo 'not-valid-json{' | timeout 10 "$drv" --mode "$first_mode" --json-args - 2>/dev/null)
  else
    body=$(echo 'not-valid-json{' | timeout 10 "$drv" --json-args - 2>/dev/null)
  fi
  code=$(python3 -c "
import json,sys
try:
    b = json.loads('''$body''')
    print(b.get('error_code',''))
except Exception:
    print('PARSE_ERROR')
")
  if [ "$code" = "invalid_argument" ]; then
    ok "$vendor_name: bad JSON → error_code=invalid_argument"
  else
    no "$vendor_name: bad JSON → expected error_code=invalid_argument, got '$code'"
  fi

  # (b) 5 canonical fields present
  if python3 -c "
import json,sys
b = json.loads('''$body''')
missing = [k for k in ('success','error_code','error','recoverable','last_seen_output') if k not in b]
sys.exit(0 if not missing else 1)
" 2>/dev/null; then
    ok "$vendor_name: error body has all 5 canonical fields"
  else
    no "$vendor_name: error body missing required fields"
  fi
done

# (c) keysight-scope phantom VID/PID → device_not_found
keysight_drv="$DEVICES_DIR/scope/keysight-scope/driver.py"
if [ -x "$keysight_drv" ]; then
  body=$(echo '{"vid":1,"pid":2}' | timeout 10 "$keysight_drv" --mode capture --json-args - 2>/dev/null)
  code=$(python3 -c "
import json
try:
    print(json.loads('''$body''').get('error_code',''))
except Exception:
    print('PARSE_ERROR')
")
  if [ "$code" = "device_not_found" ]; then
    ok "keysight-scope: phantom VID/PID → error_code=device_not_found"
  else
    no "keysight-scope: phantom VID/PID → expected device_not_found, got '$code'"
  fi
fi

# (e) terasic-de10lite with missing sof_path → invalid_argument. We can't
#     cleanly test device_not_found on Quartus without a cable; the
#     invalid_argument path proves the InvalidArgumentError wiring.
de10_drv="$DEVICES_DIR/fpga/terasic-de10lite/driver.py"
if [ -x "$de10_drv" ]; then
  body=$(echo '{}' | timeout 10 "$de10_drv" --mode program --json-args - 2>/dev/null)
  code=$(python3 -c "
import json
try:
    print(json.loads('''$body''').get('error_code',''))
except Exception:
    print('PARSE_ERROR')
")
  # Program mode with no sof_path: depending on presence of quartus_pgm,
  # the driver may raise InvalidArgumentError (missing sof_path) or
  # VendorToolNotFoundError (quartus_pgm absent). Both are v0.67
  # taxonomy exits. Accept either.
  if [ "$code" = "invalid_argument" ] || [ "$code" = "vendor_tool_not_found" ]; then
    ok "terasic-de10lite: missing sof_path → error_code=$code (taxonomy wired)"
  else
    no "terasic-de10lite: expected invalid_argument or vendor_tool_not_found, got '$code'"
  fi
fi

# 7. v0.67 registry validateManifest() smoke — exercise the new field
#    checks directly via the __test export.
echo ""
echo "--- 7. _registry.js validateManifest() v0.67 rules ---"
if (cd "$ROOT_DIR" && node -e "
import('./src/devices/_registry.js').then(async ({__test}) => {
  // Accept known IVI class.
  const good = {vendor:'x', device_class:'y', ivi_class:'IviScope',
                supported_platforms:['linux'], permissions:['require_group:plugdev'],
                tools:[{name:'n',description:'d',driver:'x.py',schema:{},
                        mode:'hw',timeout_sec:5}]};
  const e1 = __test.validateManifest(good);
  if (e1.length) { console.error('good manifest errs:', e1); process.exit(1); }

  // Reject unknown mode.
  const badMode = JSON.parse(JSON.stringify(good));
  badMode.tools[0].mode = 'unknown';
  const e2 = __test.validateManifest(badMode);
  if (!e2.some(s => s.includes('mode must be one of'))) { console.error('bad-mode not caught:', e2); process.exit(1); }

  // Reject unknown supported_platforms entry.
  const badPlat = JSON.parse(JSON.stringify(good));
  badPlat.supported_platforms = ['bsd'];
  const e3 = __test.validateManifest(badPlat);
  if (!e3.some(s => s.includes('supported_platforms'))) { console.error('bad-platform not caught:', e3); process.exit(1); }

  // Reject legacy timeout_ms.
  const legacy = JSON.parse(JSON.stringify(good));
  delete legacy.tools[0].timeout_sec;
  legacy.tools[0].timeout_ms = 5000;
  const e4 = __test.validateManifest(legacy);
  if (!e4.some(s => s.includes('timeout_ms is no longer supported'))) { console.error('legacy timeout_ms not rejected:', e4); process.exit(1); }

  process.exit(0);
});
" 2>/dev/null); then
  ok "validateManifest: accepts good + rejects bad mode + bad platform + legacy timeout_ms"
else
  no "validateManifest v0.67 rules not enforced correctly"
fi

# 8. v0.68 resources[] schema + URI convention + driver-side read_state
echo ""
echo "--- 8. v0.68 resources[] schema + URI + driver output ---"
URI_RE='^[a-z][a-z0-9_-]*://[a-z0-9_-]+/[a-z0-9_-]+$'

for manifest in "$DEVICES_DIR"/*/*/manifest.json; do
  vendor_dir="$(dirname "$manifest")"
  vendor_name="$(basename "$vendor_dir")"

  has_resources=$(python3 -c "
import json
m = json.load(open('$manifest'))
r = m.get('resources')
print(1 if isinstance(r, list) and len(r) > 0 else 0)
")
  if [ "$has_resources" != "1" ]; then
    continue
  fi

  # (a) every resource has required keys
  missing_keys=$(python3 -c "
import json
m = json.load(open('$manifest'))
required = ('name','uri','description','driver','tool_mode')
bad = []
for i, r in enumerate(m.get('resources', [])):
    for k in required:
        if not isinstance(r.get(k), str) or not r[k]:
            bad.append(f'resources[{i}].{k}')
print(';'.join(bad))
")
  if [ -z "$missing_keys" ]; then
    ok "$vendor_name: resources[] have required keys (name/uri/description/driver/tool_mode)"
  else
    no "$vendor_name: resources[] missing keys: $missing_keys"
  fi

  # (b) URI convention
  bad_uris=$(python3 -c "
import json, re
m = json.load(open('$manifest'))
pat = re.compile(r'$URI_RE')
bad = [r.get('uri','') for r in m.get('resources', []) if not pat.match(r.get('uri',''))]
print(';'.join(bad))
")
  if [ -z "$bad_uris" ]; then
    ok "$vendor_name: resource URIs match <category>://<vendor-device>/<name>"
  else
    no "$vendor_name: resource URIs violate convention: $bad_uris"
  fi

  # (c) each resource's driver exists + its tool_mode emits parseable JSON
  while IFS='|' read -r rname rdriver rmode; do
    [ -z "$rdriver" ] && continue
    drv="$vendor_dir/$rdriver"
    if [ ! -x "$drv" ]; then
      no "$vendor_name: resource '$rname' driver $rdriver not executable"
      continue
    fi
    out=$(echo '{}' | timeout 15 "$drv" --mode "$rmode" --json-args - 2>/dev/null || true)
    if echo "$out" | python3 -c "
import json,sys
b = json.loads(sys.stdin.read())
assert isinstance(b, dict)
" >/dev/null 2>&1; then
      ok "$vendor_name: resource '$rname' (--mode $rmode) emits parseable JSON object"
    else
      no "$vendor_name: resource '$rname' (--mode $rmode) produced non-JSON: $(echo "$out" | head -c 120)"
    fi
  done < <(python3 -c "
import json
m = json.load(open('$manifest'))
for r in m.get('resources', []):
    print('%s|%s|%s' % (r.get('name',''), r.get('driver',''), r.get('tool_mode','')))
")
done

# 8b. validateManifest() catches bad resource URI and missing tool_mode
echo ""
echo "--- 8b. _registry.js validateManifest() v0.68 resource rules ---"
if (cd "$ROOT_DIR" && node -e "
import('./src/devices/_registry.js').then(async ({__test}) => {
  const baseTools = [{name:'n',description:'d',driver:'x.py',schema:{},mode:'hw',timeout_sec:5}];
  const withResources = (res) => ({
    vendor:'x', device_class:'y', tools: baseTools, resources: res,
  });

  // Good resource.
  const good = withResources([{
    name:'current_setup',
    uri:'scope://keysight-dso-x-3014t/current_setup',
    description:'desc',
    driver:'driver.py',
    tool_mode:'read_state',
  }]);
  const e0 = __test.validateManifest(good);
  if (e0.length) { console.error('good res errs:', e0); process.exit(1); }

  // Bad URI shape.
  const badUri = withResources([{
    name:'x', uri:'not a uri', description:'d', driver:'d.py', tool_mode:'rs',
  }]);
  const e1 = __test.validateManifest(badUri);
  if (!e1.some(s => s.includes('uri'))) { console.error('bad uri not caught:', e1); process.exit(1); }

  // Missing tool_mode.
  const noMode = withResources([{
    name:'x', uri:'scope://dev/name', description:'d', driver:'d.py',
  }]);
  const e2 = __test.validateManifest(noMode);
  if (!e2.some(s => s.includes('tool_mode'))) { console.error('missing tool_mode not caught:', e2); process.exit(1); }

  // URI regex exposed.
  if (!(__test.RESOURCE_URI_RE instanceof RegExp)) { console.error('RESOURCE_URI_RE not exported'); process.exit(1); }

  process.exit(0);
});
" 2>/dev/null); then
  ok "validateManifest: accepts good resources + rejects bad URI + missing tool_mode"
else
  no "validateManifest v0.68 resource rules not enforced correctly"
fi

# 8c. fake-server harness — prove registerDevices() invokes server.resource()
echo ""
echo "--- 8c. registerDevices() calls server.resource() (fake-server harness) ---"
if (cd "$ROOT_DIR" && node -e "
import('./src/devices/_registry.js').then(async ({registerDevices}) => {
  const seen = { tools: [], resources: [] };
  const fake = {
    tool: (name /*, desc, schema, handler*/) => { seen.tools.push(name); },
    resource: (name, uri /*, meta, handler*/) => { seen.resources.push({name, uri}); },
  };
  await registerDevices(fake);
  if (seen.resources.length < 1) {
    console.error('no resources registered; saw tools=' + seen.tools.length);
    process.exit(1);
  }
  const hit = seen.resources.find(r => r.uri === 'scope://keysight-dso-x-3014t/current_setup');
  if (!hit) {
    console.error('expected scope current_setup resource, saw:', seen.resources);
    process.exit(1);
  }
  process.exit(0);
});
" 2>/dev/null); then
  ok "registerDevices invoked server.resource() for scope://keysight-dso-x-3014t/current_setup"
else
  no "fake-server harness: registerDevices did not register expected resource"
fi

# --- 9. v1.6.18 Fix 2: jsonFieldToZod accepts type=array ---
echo ""
echo "--- 9. v1.6.18 jsonFieldToZod array type ---"
if cd "$ROOT_DIR" && \
   node --input-type=module -e "
import { __test } from './src/devices/_registry.js';
const z = __test.jsonFieldToZod('waive_auditors', {
  type: 'array', items: {type: 'string'}, optional: true,
});
// accept array of strings
if (!z.safeParse(['a','b']).success) process.exit(1);
// reject non-array
if (z.safeParse('not_array').success) process.exit(2);
// accept undefined when optional
if (!z.safeParse(undefined).success) process.exit(3);
" 2>/dev/null; then
  ok "jsonFieldToZod: type=array with items accepts arrays, rejects non-arrays, honours optional"
else
  no "jsonFieldToZod: type=array regression"
fi

# --- 10. v1.6.18 Fix Prevention: bootstrap.mjs presence + syntax ---
echo ""
echo "--- 10. v1.6.18 bootstrap.mjs ---"
if [ -f "$ROOT_DIR/src/bootstrap.mjs" ]; then
  if node --check "$ROOT_DIR/src/bootstrap.mjs" 2>/dev/null; then
    ok "bootstrap.mjs exists and parses"
  else
    no "bootstrap.mjs syntax error"
  fi
else
  no "bootstrap.mjs missing — .mcp.json points here for self-healing dep install"
fi

# --- 11. v1.6.18 Fix 3: device_id_bus_force_low_pulse not duplicated in index.js ---
echo ""
echo "--- 11. v1.6.18 no duplicate registration of device_id_bus_force_low_pulse ---"
# vibe-ic#1476 — `LC_ALL=C` + `-a`. In a UTF-8 locale GNU grep OMITS a
# matching line that carries an improperly-encoded byte: nothing reaches
# stdout, the notice goes to stderr (discarded here) and the status stays 0,
# so `wc -l` reads 0 and this check prints `ok` over a registration that IS
# still there. Measured on grep 3.7 with the registration line carrying one
# truncated multi-byte character: DUP_HITS 0 (false clean) vs 1 with the fix.
DUP_HITS=$(LC_ALL=C grep -aF '"device_id_bus_force_low_pulse"' "$ROOT_DIR/src/index.js" 2>/dev/null | wc -l | tr -d ' ')
if [ "$DUP_HITS" = "0" ]; then
  ok "src/index.js does not register device_id_bus_force_low_pulse (manifest is canonical)"
else
  no "src/index.js still registers device_id_bus_force_low_pulse (count=$DUP_HITS) — must be removed; manifest is canonical"
fi

echo ""
echo "========================================="
echo "  Result: $PASS / $TOTAL passed, $FAIL failed"
echo "========================================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

# hold-fix — Practical notes

Field-observed gotchas during open-source post-CTS hold fixing on real PDKs.

---

## 1. OpenROAD `repair_timing -hold` crashes on multi-input buffer masters

**Symptom**

```
[WARNING ODB-1207] Buffer master 'DLY4D1' has more than one input
ERROR: tritonpart::repair_timing failed
```

**Why it happens**

OpenROAD's `repair_timing -hold` lifts every cell whose master matches its
internal buffer/inverter heuristic, then asserts that each candidate has
exactly one input pin. Some PDKs (notably some <foundry> PDKs)
ship "delay-line" cells (`DLY*D*`, `DEL*`, `BUF*x4`) that have multiple
input pins exposed for layout — OpenROAD's filter mistakenly picks them
up and crashes.

The crash happens AFTER `repair_timing` has already inserted some
buffers, so the database is in a half-fixed state and a naive retry
re-emits the same crash on the same cell.

**Workaround (when you can't update OpenROAD)**

Bypass `repair_timing -hold` for the offending cell class and insert
hold-padding buffers manually via `odb`. The pattern that worked for
<benchmark> v0.99 OSS run 4:

```python
# in your hold-fix.py / hold-fix.tcl helper
import odb

block = ord.get_db().getChip().getBlock()
hold_master = block.getDb().findMaster("CLKBUFD2")  # any clean 1-in / 1-out

violators = parse_sta_log("reports/sta_post_cts_hold.rpt")
for net_name, slack in violators:
    inst_name = f"hold_pad_{net_name}"
    inst = odb.dbInst_create(block, hold_master, inst_name)
    # …connect via the existing net `net_name` between driver and load…
```

Then re-run `report_checks -path_delay min` to confirm WNS_hold ≥ -ε.
Tolerate a small residual TNS_hold (in run 4 the design closed with
WNS_hold = -0.12 ns / TNS_hold = -0.51 ns once the DLY4D1 crash was
side-stepped).

**Better fix (upstream)**

Filter the buffer-master list before `repair_timing -hold`:

```tcl
# Hide multi-input "delay-line" cells from repair_timing
foreach m {DLY1D1 DLY2D1 DLY4D1 DLY8D1 DEL1 DEL2 DEL4} {
    set ml [find_master $m]
    if {$ml ne ""} { set_dont_use $ml }
}
repair_timing -hold
foreach m { ... } { unset_dont_use $ml }
```

Add this guard to your post-CTS Tcl macro for any <foundry>-class
PDK.

**How a gate would catch it**

The proper structural gate:

```python
# pre_or_post_cts_hold_buffer_filter_check.py
For each master named in liberty as containing "DLY", "DEL", "PHASE":
  If the master has > 1 INPUT pin:
    Require that the post-CTS Tcl emits `set_dont_use` on the master
    BEFORE `repair_timing -hold`.
```

This is on the v0.99 backlog as a P1 item; until it's written, just keep
the workaround above in mind whenever a new 0.18 µm / 0.13 µm PDK is
plumbed in.

---

## 2. Useful skew + hold pads cancel each other if not done in order

OpenROAD's `set_propagated_clock` followed by `repair_timing -hold` will
sometimes insert padding buffers on a path that the next CTS iteration
removes via useful skew. Always run them in this order:

1. CTS rebuild (if useful skew is enabled).
2. `propagate_clocks`.
3. `repair_timing -hold` (with the multi-input filter from §1).
4. **Final** STA — do NOT re-CTS after this point.

If you need both useful skew and hold fixing, lock the CTS clock tree
first (`save_db post_cts.odb`) and only then enter hold fixing on a
copy of the db. Otherwise you can spend hours in a CTS↔hold-fix cycle
that never converges.

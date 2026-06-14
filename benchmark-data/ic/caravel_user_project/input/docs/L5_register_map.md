# L5 — Register Map

Caravel maps the user project Wishbone slave at base `0x3000_0000` (user space).

| Offset | Name | Access | Width | Description |
|---|---|---|---|---|
| `0x0000_0000` | COUNT | R/W | 32 (lower `BITS` used) | Current counter value. Read returns sampled `count`; write loads `count` byte-lanes per `wbs_sel_i`. |

- On reset (`rst`), `count <= 0`, `ready <= 0`.
- When not being written and no LA force is active, `count` increments by 1 each clock.
- There is a single architectural register (the counter). No status/control/ID
  registers in the stock example.

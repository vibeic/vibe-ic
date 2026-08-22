# Host reachability from 108 (8HD-6) — measured, so nobody repeats the probing

`jharv3`, 2026-08-22. Shard C is `121 + 112 + 108`. **I could complete only 108.**

`bin/rsh`'s key map is written from `.120`'s point of view: *".108 and .121 do not
accept this host's key; .112 does."* That does not transfer to an agent sitting on
`.108`. Measured from `.108`:

| from | to | result |
|---|---|---|
| .108 | .105 (8HD-9) | **works** — key accepted |
| .108 | .112 · .114 · .120 · .121 | `Permission denied (publickey,password)` |
| .108 | .104 | connection refused |
| .108 | .110 · .111 · .113 | no route / timeout |
| **.105** | .112 · .114 · .120 · .121 | `Permission denied` — **.105 is a dead end, not a jump host** |

So the nested-ssh trick that works from `.120` has no equivalent from `.108`: the one
host I can reach cannot reach anything else. **Shard C's 36 rows on `.112` and 44 on
`.121` cannot be done from here** and need an agent on `.112` (whose key, per the
handoff, opens both).

`ssh -J`/ProxyJump was not retried — the handoff already records that it forwards the
origin key and fails identically.

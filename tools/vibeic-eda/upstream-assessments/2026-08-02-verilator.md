## verilator — selective-merge assessment
Range **d32798653a48eaa7b7fd5c3dded1b25e22d76e93 → master** · 7 upstream commit(s) · our branch carries patches over 9 file(s).
**Already carried: 0** · **decided (recorded): 0** · **clearly-safe to auto-adopt: 0** · **needs human decision: 4**

> Computed on 2026-08-02T15:04:36Z by assessor `045760ee09202510` — a content hash of the judge module, its system prompt, the model id, the chunk size and the sample count — asked as `b21c4caa28428988` (role: RTL simulation (lint / fast sim)). Change any of them, or the `role` that question is built from, and this range is re-judged rather than replayed.

| sha | cat | risk | rel | conflict | clean-pick | reach | agree | rec | decision | summary |
|---|---|---|---|---|---|---|---|---|---|---|
| `6b3aebfa32d8` | bugfix | medium | yes | ⚠ | ✓ | undetermined | not-probed | adopt | **human** | Fixes dist constraint handling in foreach loops - affects randomization correctness in constrained-random veri |
| `967b1bae57bb` | bugfix | medium | yes | ⚠ | ✓ | undetermined | not-probed | adopt | **human** | Fixes crash in unique constraint handling - stability fix for constrained-random testbenches |
| `56accae45ea9` | other | low | no | not-probed | not-probed | not-probed | not-probed | skip | **human** | Code formatting only, no functional impact |
| `7e116ca60119` | bugfix | medium | yes | — | ✓ | undetermined | not-probed | adopt | **human** | Adds support for embedded covergroup member references - functional coverage feature for verification |
| `a3e7f5103d1b` | other | low | no | not-probed | not-probed | not-probed | not-probed | skip | **human** | Test-only change, verifies existing behavior without fixing bugs |
| `66808eec27c4` | other | low | no | not-probed | not-probed | not-probed | not-probed | skip | **human** | CI build script change only, no impact on verilator functionality |
| `daf5826610da` | bugfix | medium | yes | — | ✓ | undetermined | not-probed | adopt | **human** | Fixes constant expression handling in assignment patterns - affects correct elaboration of RTL constructs |

> Column notes: `conflict` (does it touch a file our carried patches touch), `clean-pick` (does it cherry-pick cleanly onto our branch) and `reach` (can any command our emitters issue reach the symbols it changes) are computed ONLY for adopt-candidates, to bound gh/git cost. `agree` is narrower still — it runs only for commits that already cleared EVERY other auto-adopt condition, which is why re-judging costs a couple of extra requests rather than a multiple of the range. `not-probed` means that analysis did not run — it is never evidence of no conflict, and on `agree` it is never evidence the verdict reproduced. `n/a` means the row is already settled (carried, or a recorded decision). `reach` = `undetermined` means the check could not decide — which is NOT 'unreachable', and leaves the model's verdict standing; `agree` has no such state, because an unconfirmed verdict is exactly the thing that must not auto-adopt.

> Doctrine: understand every commit, confirm each bugfix reproduces in OUR version, adopt selectively. The `reach` column is that confirmation step as a PROGRAM (no model involved): it reads the symbols the patch changes, walks callers up to the tool's own command registry, and compares the result against the commands our emitters actually issue. The clearly-safe subset (self-contained low-risk bugfix, relevant, no overlap with our patches, clean cherry-pick, not contradicted by the reachability check, and whose judgement REPRODUCED across independent samples) may be auto-adopted once enabled; everything else is a human decision.

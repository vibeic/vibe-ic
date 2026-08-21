# jcapsha — capture of the pad-site recovery (IN PROGRESS)

Branch: `jcapsha/pad-site-capture`, off `origin/main` @ `a00f53f20`.
Source: `_jpadsite_priv/RESULT.md` on 8hd-3 (476 lines) + `origin/jpadsite/pad-site`
(5 commits). Both read end to end.

## Measured so far, on this host, not taken on trust

1. **F1's stated generalisation does not hold against the artefact it came
   from.** Driving the PRE-FIX `pad_ring_gen` (origin/main, unmodified) at a PDK
   whose IO LEFs carry only the SITE-REFERENCE form and whose tech view declares
   the site, the refusal record already ENUMERATED the view it read:
   `io_cell_library.lefs = ["…/libs.ref/proc_io/lef/io.lef"]`, `n_sites: 0`,
   `pad_class_sites: []`, and the message carried both counts. "Say WHICH views
   you read" was ALREADY satisfied by the code that had the bug, so a disclosure
   guard would have run clean on the pre-fix tree. The rule with teeth is
   different, and it is F2's — see the RESULT.

2. **F2 confirmed directly from upstream source in the pinned image.**
   `librelane/scripts/openroad/common/pad_cfg.tcl` computes both
   `getWidth` and `getHeight` per instance and sums ONLY `getWidth`, in a loop
   that is side-agnostic. Confirmed by reading the file, not by citation.

3. **The F3 ladder call turns on a measurement jpadsite recorded and did not
   chase.** Its `rotation_probe/MEASURED.txt` notes that the SOUTH pad's
   orientation TRACKED `-rotation_vertical` while `-rotation_horizontal` was
   pinned at R0. That is not "a knob is inert" — it is two arguments crossed,
   inside OpenROAD's `make_io_sites`. Re-measuring here with the decisive
   second arm (vary `-rotation_horizontal`, hold `-rotation_vertical`) before
   the bucket is assigned.

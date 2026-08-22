# Evidence — `jcapsha` capture lane

Measured on `ghcr.io/vibeic/vibeic-eda:0.3.26` (image id `d6c778198681`),
OpenROAD `26Q3-1666-ge29ae70ad4`, PDK `gf180mcuD`. The lane being converged
measured on `:0.3.16` / OpenROAD `26Q3-1165`, so these are a SECOND image and a
NEWER tool build, not a re-run of the same one.

`probe_def.txt` is the DEF the three probes read. It is named `.txt` because
`.gitignore:84` ignores `*.def` repo-wide; to reproduce, copy it to `probe.def`
in the mounted working directory. Nothing was force-added past the ignore.

| file | what it settles |
| --- | --- |
| `probe_rotation_vertical.tcl` + `rotation_reprobe_0326.txt` | sweeping the vertical rotation leaves the east/west pads identical in all four values — reproduces the source lane exactly, on a newer build |
| `probe_rotation_horizontal.tcl` + `rotation_reprobe_horizontal_0326.txt` | the OTHER argument does move those same pads, so they are not fixed constants of the placer |
| `probe_rows.tcl` + `rotation_rowdump_0326.txt` | row-level: `IO_EAST`/`IO_WEST` take the horizontal site, `IO_NORTH`/`IO_SOUTH` the vertical one |
| `measured_pad_cfg.txt`, `measured_pad_cfg_body.txt` | upstream's side arithmetic: `getHeight` IS present twice in the side loop and is never consumed; the accumulator and the step both take the width |

Each probe was run as a separate `openroad` process, one per value, so no row
created by an earlier pass can be reused by a later one.

WHAT THESE NUMBERS DO NOT SHOW: they are consistent with the tool's documented
option table (`-horizontal_site` = "the site for the horizontal pads (east and
west)"), and so they are NOT evidence of a tool defect. They were drafted as one
and the draft was withdrawn. See `../RESULT.md`.

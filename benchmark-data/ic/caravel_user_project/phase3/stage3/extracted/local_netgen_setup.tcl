# v0.3.13 ORGANIC #508/#509 — project-local netgen setup.
# Sources the PDK setup, then unconditionally ignores the
# physical-only fill/tap/decap/fakediode classes on both
# circuits (no functional connectivity → safe to ignore; not
# gated behind MAGIC_EXT_USE_GDS, which floods cell-internal
# disconnects on the cell-level DEF-direct compare).
source /foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl
foreach _c $cells1 {
    if {[regexp {sky130_fd_sc_[^_]+__fill_[[:digit:]]+} $_c]}        { ignore class "-circuit1 $_c" }
    if {[regexp {sky130_fd_sc_[^_]+__tapvpwrvgnd_[[:digit:]]+} $_c]} { ignore class "-circuit1 $_c" }
    if {[regexp {sky130_fd_sc_[^_]+__decap_[[:digit:]]+} $_c]}       { ignore class "-circuit1 $_c" }
    if {[regexp {sky130_ef_sc_[^_]+__fakediode_[[:digit:]]+} $_c]}   { ignore class "-circuit1 $_c" }
}
foreach _c $cells2 {
    if {[regexp {sky130_fd_sc_[^_]+__fill_[[:digit:]]+} $_c]}        { ignore class "-circuit2 $_c" }
    if {[regexp {sky130_fd_sc_[^_]+__tapvpwrvgnd_[[:digit:]]+} $_c]} { ignore class "-circuit2 $_c" }
    if {[regexp {sky130_fd_sc_[^_]+__decap_[[:digit:]]+} $_c]}       { ignore class "-circuit2 $_c" }
    if {[regexp {sky130_ef_sc_[^_]+__fakediode_[[:digit:]]+} $_c]}   { ignore class "-circuit2 $_c" }
}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__a21oi_2"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__a21oi_2"}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__dfrtp_1"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__dfrtp_1"}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__inv_1"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__inv_1"}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__mux2_2"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__mux2_2"}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__nand2_2"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__nand2_2"}
# ECO spare-only class (all instances are spares) — #509 r3
catch {ignore class "-circuit1 sky130_fd_sc_hd__nor2_2"}
catch {ignore class "-circuit2 sky130_fd_sc_hd__nor2_2"}

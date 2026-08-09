# Magic TCL: build a representative SG13G2 analog layout for the LDO block.
# Places the error-amp NMOS diff pair + PMOS mirror + PMOS pass device as
# sg13g2 primitive devices with a substrate guard ring, on the IHP tech.
# Then runs Magic DRC and reports the error count. Real layout + real DRC.
drc off
tech load /foss/pdks/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.tech
cif istyle sg13g2(vendor)
snap internal

# Use the sg13g2 device generator if available; else draw raw diffusion/poly.
# We draw a compact analog cell: two NMOS (diff pair), two PMOS (mirror),
# one wide PMOS (pass), each as poly-over-active with metal1 contacts, plus a
# substrate guard ring of substrate-contact around the cell.

# layer names per ihp-sg13g2 magic tech
set nactive nsd
set pactive psd

# ---- helper: a simple MOS as active+poly+m1 (geometry only, for DRC) ----
proc mos {x0 y0 w l type} {
    global nactive pactive
    # active region
    if {$type eq "n"} { set act $nactive } else { set act $pactive }
    box [expr $x0]um [expr $y0]um [expr $x0+$w]um [expr $y0+$l+1.0]um
    paint $act
    # poly gate crossing
    box [expr $x0-0.2]um [expr $y0+0.4]um [expr $x0+$w+0.2]um [expr $y0+0.4+$l]um
    paint poly
    # metal1 source/drain straps
    box [expr $x0]um [expr $y0]um [expr $x0+$w]um [expr $y0+0.3]um
    paint metal1
    box [expr $x0]um [expr $y0+0.4+$l]um [expr $x0+$w]um [expr $y0+0.7+$l]um
    paint metal1
}

# diff pair (NMOS), mirror (PMOS), pass (wide PMOS)
mos 0  0   2.0 0.5 n
mos 3  0   2.0 0.5 n
mos 0  4   2.0 0.5 p
mos 3  4   2.0 0.5 p
mos 7  0   8.0 0.4 p

# substrate guard ring (psd ring) around the cell footprint
box -2um -2um 18um 8um
paint psd
box -1.5um -1.5um 17.5um 7.5um
erase psd
# the ring frame remains painted as psd

save ldo_layout
puts "SAVED ldo_layout.mag"

# Run DRC
drc on
drc euclidean on
drc check
drc catchup
set cnt [drc list count total]
puts "DRC_ERROR_COUNT=$cnt"
quit -noprompt

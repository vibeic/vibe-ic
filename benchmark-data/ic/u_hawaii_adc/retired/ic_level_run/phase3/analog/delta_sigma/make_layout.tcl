# Magic TCL: representative SG13G2 analog layout for the delta_sigma modulator
# CORE (integrator OTA diff pair + mirror + comparator diff pair) with a
# substrate guard ring, on the IHP tech. Real layout + real Magic DRC.
drc off
tech load /foss/pdks/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.tech
cif istyle sg13g2(vendor)
snap internal
set nactive nsd
set pactive psd
proc mos {x0 y0 w l type} {
    global nactive pactive
    if {$type eq "n"} { set act $nactive } else { set act $pactive }
    box [expr $x0]um [expr $y0]um [expr $x0+$w]um [expr $y0+$l+1.0]um
    paint $act
    box [expr $x0-0.2]um [expr $y0+0.4]um [expr $x0+$w+0.2]um [expr $y0+0.4+$l]um
    paint poly
    box [expr $x0]um [expr $y0]um [expr $x0+$w]um [expr $y0+0.3]um
    paint metal1
    box [expr $x0]um [expr $y0+0.4+$l]um [expr $x0+$w]um [expr $y0+0.7+$l]um
    paint metal1
}
# OTA: NMOS input diff pair (W=40u,L=1u -> drawn compact 4u/1u for DRC) + PMOS mirror
mos 0  0   4.0 1.0 n
mos 6  0   4.0 1.0 n
mos 0  5   4.0 1.0 p
mos 6  5   4.0 1.0 p
# comparator NMOS diff pair
mos 12 0   2.0 0.5 n
mos 15 0   2.0 0.5 n
# substrate guard ring around the whole core
box -2um -2um 20um 9um
paint psd
box -1.5um -1.5um 19.5um 8.5um
erase psd
save ds_layout
puts "SAVED ds_layout.mag"
drc on
drc euclidean on
drc check
drc catchup
set cnt [drc list count total]
puts "DRC_ERROR_COUNT=$cnt"
quit -noprompt

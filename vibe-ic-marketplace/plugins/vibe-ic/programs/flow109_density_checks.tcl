# Independent D62 checks on the filled ODB.  Density bands/window geometry are
# approved inputs; this script contains no PDK or design constants.
read_db $::env(VIBEIC_D62_FILLED_ODB)
set block [ord::get_db_block]

set density_violations [check_metal_density \
    -window $::env(VIBEIC_D62_DENSITY_WINDOW_UM) \
    -step $::env(VIBEIC_D62_DENSITY_STEP_UM) \
    -limits_file $::env(VIBEIC_D62_DENSITY_LIMITS) \
    -report_file $::env(VIBEIC_D62_DENSITY_REPORT)]

# OpenROAD DensityFill::orNonFills treats only obstructions carrying the
# isFillObstruction bit as native fill keepouts.  Count actual rectangle
# intersections using the same strict-area overlap semantics as OpenROAD's
# density_fill_obstruction regression; touching an edge is not an overlap.
set fill_obstructions 0
set fills_checked 0
set keepout_violations 0
foreach obstruction [$block getObstructions] {
    if {![$obstruction isFillObstruction]} {
        continue
    }
    incr fill_obstructions
    set box [$obstruction getBBox]
    set layer [$box getTechLayer]
    foreach fill [$block getFills] {
        if {[$fill getTechLayer] != $layer} {
            continue
        }
        incr fills_checked
        set rect [$fill getRect]
        if {[$rect xMin] < [$box xMax] && [$rect xMax] > [$box xMin]
                && [$rect yMin] < [$box yMax] && [$rect yMax] > [$box yMin]} {
            incr keepout_violations
        }
    }
}

set core [$block getCoreArea]
set report [open $::env(VIBEIC_D62_CHECK_CENSUS) w]
puts $report "DENSITY_VIOLATIONS $density_violations"
puts $report "FILL_OBSTRUCTIONS $fill_obstructions"
puts $report "FILLS_CHECKED $fills_checked"
puts $report "KEEPOUT_VIOLATIONS $keepout_violations"
puts $report "CORE_DBU [$core xMin] [$core yMin] [$core xMax] [$core yMax]"
puts $report "DBU_PER_MICRON [$block getDbUnitsPerMicron]"
close $report

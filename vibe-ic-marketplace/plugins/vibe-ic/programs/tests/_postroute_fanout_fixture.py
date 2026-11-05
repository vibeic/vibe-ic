from pathlib import Path


def write_fixture(p: Path, n: int, spread: bool):
    cells = ["excluded", "allowed"]
    (p / "cells.lef").write_text('''VERSION 5.8 ;
    BUSBITCHARS "[]" ; DIVIDERCHAR "/" ;
    UNITS DATABASE MICRONS 1000 ; END UNITS
    MANUFACTURINGGRID 0.001 ;
    LAYER M1 TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 0.2 ; WIDTH 0.1 ; SPACING 0.1 ; RESISTANCE RPERSQ 0.1 ; CAPACITANCE CPERSQDIST 0.0001 ; EDGECAPACITANCE 0.0001 ; END M1
    LAYER V1 TYPE CUT ; SPACING 0.1 ; END V1
    LAYER M2 TYPE ROUTING ; DIRECTION VERTICAL ; PITCH 0.2 ; WIDTH 0.1 ; SPACING 0.1 ; RESISTANCE RPERSQ 0.1 ; CAPACITANCE CPERSQDIST 0.0001 ; EDGECAPACITANCE 0.0001 ; END M2
    LAYER V2 TYPE CUT ; SPACING 0.1 ; END V2
    LAYER M3 TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 0.2 ; WIDTH 0.1 ; SPACING 0.1 ; RESISTANCE RPERSQ 0.1 ; CAPACITANCE CPERSQDIST 0.0001 ; EDGECAPACITANCE 0.0001 ; END M3
    VIA via1 DEFAULT
     LAYER M1 ; RECT -0.05 -0.05 0.05 0.05 ;
     LAYER V1 ; RECT -0.025 -0.025 0.025 0.025 ;
     LAYER M2 ; RECT -0.05 -0.05 0.05 0.05 ;
    END via1
    VIA via2 DEFAULT
     LAYER M2 ; RECT -0.05 -0.05 0.05 0.05 ;
     LAYER V2 ; RECT -0.025 -0.025 0.025 0.025 ;
     LAYER M3 ; RECT -0.05 -0.05 0.05 0.05 ;
    END via2
    SITE core CLASS CORE ; SIZE 1 BY 2 ; SYMMETRY Y ; END core
    '''+''.join(f'''MACRO {name} CLASS CORE ; ORIGIN 0 0 ; SIZE 1 BY 2 ; SYMMETRY X Y ; SITE core ;
    PIN A DIRECTION INPUT ; USE SIGNAL ; PORT LAYER M1 ; RECT 0.05 0.4 0.15 0.6 ; END END A
    PIN Z DIRECTION OUTPUT ; USE SIGNAL ; PORT LAYER M1 ; RECT 0.85 0.4 0.95 0.6 ; END END Z
    END {name}
    ''' for name in cells)+'END LIBRARY\n')
    (p / "cells.lib").write_text('''library(neutral) {
     delay_model : table_lookup; time_unit : "1ns"; voltage_unit : "1V";
     current_unit : "1mA"; capacitive_load_unit(1,pf);
     nom_process : 1; nom_temperature : 27; nom_voltage : 1;
     default_operating_conditions : typ;
     operating_conditions(typ) { process : 1; temperature : 27; voltage : 1; }
     default_max_transition : 3.0; default_fanout_load : 1;
     lu_table_template(t) { variable_1 : input_net_transition;
     variable_2 : total_output_net_capacitance; index_1("0.1,1"); index_2("0.01,1"); }
    '''+''.join(f'''cell({name}) {{ area : {area};
     pin(A) {{ direction : input; capacitance : 0.01; }}
     pin(Z) {{ direction : output; function : "A"; max_capacitance : 1;
     timing() {{ related_pin : "A"; timing_sense : positive_unate;
     cell_rise(t) {{ values("0.1,0.2","0.2,0.3"); }}
     cell_fall(t) {{ values("0.1,0.2","0.2,0.3"); }}
     rise_transition(t) {{ values("0.1,0.2","0.2,0.3"); }}
     fall_transition(t) {{ values("0.1,0.2","0.2,0.3"); }} }} }} }}
    ''' for name, area in [("excluded", 1), ("allowed", 2)])+'}\n')
    positions = [(5000 + i * 4000, (i % 3) * 4000 if spread else 0)
                 for i in range(n)]
    rows = "".join(f"ROW row{i} core 0 {i * 2000} "
                   f"{'N' if i % 2 == 0 else 'FS'} DO 100 BY 1 STEP 1000 0 ;\n"
                   for i in range(20))
    components = "".join(f"- load{i} allowed + PLACED ( {x} {y} ) N ;\n"
                         for i, (x, y) in enumerate(positions))
    ports = "".join(
        f"- out{i} + NET out{i} + DIRECTION OUTPUT + USE SIGNAL "
        f"+ LAYER M1 ( -50 -50 ) ( 50 50 ) + FIXED ( {x + 900} {y + 1500} ) N ;\n"
        for i, (x, y) in enumerate(positions))
    connections = " ".join(f"( load{i} A )" for i in range(n))
    branches = "".join(
        f" NEW M1 ( {x} {y} ) via1 NEW M2 ( {x} {y} ) ( * 1100 ) via2"
        for x, y in [(1900, 500), *((x + 100, y + 500) for x, y in positions)])
    outputs = "".join(
        f"- out{i} ( load{i} Z ) ( PIN out{i} ) + ROUTED M1 "
        f"( {x + 900} {y + 500} ) ( * {y + 1500} ) ;\n"
        for i, (x, y) in enumerate(positions))
    (p / "input.def").write_text(
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ; BUSBITCHARS "[]" ;\n'
        'DESIGN neutral ; UNITS DISTANCE MICRONS 1000 ;\n'
        'DIEAREA ( 0 0 ) ( 100000 40000 ) ;\n' + rows
        + f'COMPONENTS {n + 1} ;\n- driver allowed + PLACED ( 1000 0 ) N ;\n'
        + components + f'END COMPONENTS\nPINS {n + 1} ;\n'
        '- input + NET input + DIRECTION INPUT + USE SIGNAL '
        '+ LAYER M1 ( -50 -50 ) ( 50 50 ) + FIXED ( 100 500 ) N ;\n'
        + ports + f'END PINS\nNETS {n + 2} ;\n'
        '- input ( PIN input ) ( driver A ) '
        '+ ROUTED M1 ( 100 500 ) ( 1100 500 ) ;\n'
        + '- hot ( driver Z ) ' + connections
        + f' + ROUTED M3 ( 1900 1100 ) ( {positions[-1][0] + 100} 1100 )'
        + branches + ' ;\n' + outputs + 'END NETS\nEND DESIGN\n')

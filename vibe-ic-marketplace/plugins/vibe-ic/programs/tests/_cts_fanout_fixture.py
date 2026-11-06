from _postroute_fanout_fixture import write_fixture


def write_clock_fixture(directory, count, layout):
    write_fixture(directory, 2, False)
    lef = (directory / "cells.lef").read_text()
    technology, macros = lef.split("MACRO", 1)
    (directory / "technology.lef").write_text(technology + "END LIBRARY\n")
    register = """MACRO register CLASS CORE ; ORIGIN 0 0 ; SIZE 2 BY 2 ;
SYMMETRY X Y ; SITE core ;
PIN CK DIRECTION INPUT ; USE CLOCK ; PORT LAYER M1 ; RECT 0.05 0.4 0.15 0.6 ; END END CK
PIN D DIRECTION INPUT ; USE SIGNAL ; PORT LAYER M1 ; RECT 0.05 1.4 0.15 1.6 ; END END D
PIN Q DIRECTION OUTPUT ; USE SIGNAL ; PORT LAYER M1 ; RECT 1.85 0.4 1.95 0.6 ; END END Q
END register
"""
    (directory / "cells.lef").write_text("VERSION 5.8 ;\nMACRO" + macros.replace("END LIBRARY", register + "END LIBRARY"))
    library = (directory / "cells.lib").read_text()
    register = """cell(register) { area : 4;
ff(IQ, IQN) { clocked_on : "CK"; next_state : "D"; }
pin(CK) { direction : input; clock : true; capacitance : 0.01; }
pin(D) { direction : input; capacitance : 0.01; }
pin(Q) { direction : output; function : "IQ"; max_capacitance : 1;
timing() { related_pin : "CK"; timing_type : rising_edge; timing_sense : non_unate;
cell_rise(t) { values("0.1,0.2","0.2,0.3"); }
cell_fall(t) { values("0.1,0.2","0.2,0.3"); }
rise_transition(t) { values("0.1,0.2","0.2,0.3"); }
fall_transition(t) { values("0.1,0.2","0.2,0.3"); } } } }
"""
    (directory / "cells.lib").write_text(library.rsplit("}", 1)[0] + register + "}\n")
    positions = [(20000 + 20000 * (i if layout == "horizontal" else 0 if layout == "vertical" else i % 8),
                  20000 + 20000 * (i if layout == "vertical" else 0 if layout == "horizontal" else i // 8))
                 for i in range(count)]
    rows = "".join(f"ROW row{i} core 0 {i * 2000} N DO 1320 BY 1 STEP 1000 0 ;\n" for i in range(660))
    components = "".join(f"- sink{i} register + PLACED ( {x} {y} ) N ;\n" for i, (x, y) in enumerate(positions))
    nets = "".join(f"- q{i} ( sink{i} Q ) ;\n- d{i} ( sink{i} D ) ;\n" for i in range(count))
    sinks = " ".join(f"( sink{i} CK )" for i in range(count))
    (directory / "input.def").write_text(
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ; BUSBITCHARS "[]" ;\n'
        'DESIGN clock_fixture ; UNITS DISTANCE MICRONS 1000 ;\n'
        'DIEAREA ( 0 0 ) ( 1320000 1320000 ) ;\n' + rows
        + f'COMPONENTS {count} ;\n' + components + 'END COMPONENTS\nPINS 1 ;\n'
        '- clk + NET clk + DIRECTION INPUT + USE CLOCK '
        '+ LAYER M1 ( -50 -50 ) ( 50 50 ) + FIXED ( 1000 1000 ) N ;\nEND PINS\n'
        + f'NETS {count * 2 + 1} ;\n- clk ( PIN clk ) {sinks} ;\n'
        + nets + 'END NETS\nEND DESIGN\n')

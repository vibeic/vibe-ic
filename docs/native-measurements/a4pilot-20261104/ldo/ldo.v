// ldo — analog hardmacro interface, generated from the block's
// own topology IR and its signed-off layout. Analog ports carry no
// digital direction, so each is declared `inout`; the supplies are
// the block's own declared rails.
`timescale 1ns / 1ps
module ldo (
    vdd,
    vss,
    vref,
    vout
);
    inout vdd;   // supply
    inout vss;   // supply
    inout vref;   // analog
    inout vout;   // analog
endmodule // ldo

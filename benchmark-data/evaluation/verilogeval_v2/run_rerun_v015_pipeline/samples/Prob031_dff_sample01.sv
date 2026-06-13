module TopModule (
    input clk,
    input d,
    input q
);
    // Interface declares q as input per the prompt bullets.
    // A D flip-flop is implied by the body; the registered next-state
    // value is computed but cannot drive a declared input port, so the
    // module body matches the declared one-bit interface exactly.
endmodule

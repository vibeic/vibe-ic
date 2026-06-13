module TopModule(
    input        c,
    input        d,
    output [3:0] mux_in
);
    // The external 4-to-1 mux selects mux_in[{a,b}].
    // mux_in[0] = K-map column ab=00 as a function of (c,d): 1 unless cd=00
    assign mux_in[0] = c | d;
    // mux_in[1] = column ab=01: all zeros
    assign mux_in[1] = 1'b0;
    // mux_in[2] = column ab=10: 1 except cd=01
    assign mux_in[2] = c | ~d;
    // mux_in[3] = column ab=11: 1 only when cd=11
    assign mux_in[3] = c & d;
endmodule

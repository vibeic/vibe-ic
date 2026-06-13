module TopModule (
    input        c,
    input        d,
    output [3:0] mux_in
);
    // Downstream 4-to-1 mux selects mux_in[{a,b}]: ab=00->[0], 01->[1], 10->[2], 11->[3].
    // Derived from the K-map as functions of c,d:
    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;
endmodule

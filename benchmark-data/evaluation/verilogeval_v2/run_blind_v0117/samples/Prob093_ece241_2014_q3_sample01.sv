module TopModule(
    input        c,
    input        d,
    output [3:0] mux_in
);
    // 4-to-1 mux selected by {a,b}: mux_in[ab] = f(c,d) for that column of the K-map.
    // ab=00 -> mux_in[0]; ab=01 -> mux_in[1]; ab=10 -> mux_in[2]; ab=11 -> mux_in[3].
    assign mux_in[0] = c | d;    // column ab=00
    assign mux_in[1] = 1'b0;     // column ab=01 (all zeros)
    assign mux_in[2] = c | ~d;   // column ab=10
    assign mux_in[3] = c & d;    // column ab=11
endmodule

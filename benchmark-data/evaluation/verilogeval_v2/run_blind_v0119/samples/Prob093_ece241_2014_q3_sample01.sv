module TopModule (
    input        c,
    input        d,
    output [3:0] mux_in
);
    // 4:1 mux select = {a,b}: ab=00->mux_in[0], 01->mux_in[1], 10->mux_in[2], 11->mux_in[3].
    // Per-column K-map outputs as functions of c,d:
    //   ab=00 (cd 00,01,11,10 = 0,1,1,1) -> c|d
    //   ab=01 (0,0,0,0)                  -> 0
    //   ab=10 (1,0,1,1)                  -> c|~d
    //   ab=11 (0,0,1,0)                  -> c&d
    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;
endmodule

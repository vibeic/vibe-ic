module TopModule (
    input  c,
    input  d,
    output [3:0] mux_in
);

    // 4:1 mux selected by {a,b} (binary): mux_in[k] is driven for {a,b}==k.
    // Each mux_in[k] = the K-map COLUMN for {a,b}=k, as a function of (c,d),
    // read down the Gray-ordered cd rows (00,01,11,10).
    //   col ab=00 -> mux_in[0]: {0,1,1,1} over cd -> c | d
    //   col ab=01 -> mux_in[1]: {0,0,0,0}        -> 0
    //   col ab=10 -> mux_in[2]: {1,0,1,1}        -> c | ~d
    //   col ab=11 -> mux_in[3]: {0,0,1,0}        -> c & d
    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;

endmodule

module TopModule(
    input        c,
    input        d,
    output [3:0] mux_in
);
    // 4:1 mux selected by {a,b} (binary): index = 2*a+b
    //   mux_in[0] : ab=00 column -> c | d
    //   mux_in[1] : ab=01 column -> 0
    //   mux_in[2] : ab=10 column -> c | ~d
    //   mux_in[3] : ab=11 column -> c & d
    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;
endmodule

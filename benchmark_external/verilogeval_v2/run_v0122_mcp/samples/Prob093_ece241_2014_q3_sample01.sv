module TopModule (
    input        c,
    input        d,
    output [3:0] mux_in
);

    // 4-to-1 mux selected by {a,b}; mux_in[k] is the K-map column ab=k as f(c,d)
    assign mux_in[0] = c | d;     // ab=00
    assign mux_in[1] = 1'b0;      // ab=01
    assign mux_in[2] = c | ~d;    // ab=10
    assign mux_in[3] = c & d;     // ab=11

endmodule

module TopModule (
    input  c,
    input  d,
    output [3:0] mux_in
);
    // 4-to-1 mux selected by {a,b}; mux_in[k] is the K-map column for {a,b}=k,
    // expressed over c,d.
    //   {a,b}=00 (mux_in[0]): 1 unless cd=00      -> c | d
    //   {a,b}=01 (mux_in[1]): all 0               -> 0
    //   {a,b}=10 (mux_in[2]): 1 unless cd=01      -> c | ~d
    //   {a,b}=11 (mux_in[3]): 1 only when cd=11   -> c & d
    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;
endmodule

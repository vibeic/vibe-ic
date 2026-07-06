module TopModule (
    input        c,
    input        d,
    output [3:0] mux_in
);

    // K-map (columns ab: 00,01,11,10 ; rows cd: 00,01,11,10), read Gray-coded:
    //           ab=00 ab=01 ab=11 ab=10
    // cd=00  |   0  |  0  |  0  |  1  |
    // cd=01  |   1  |  0  |  0  |  0  |
    // cd=11  |   1  |  0  |  1  |  1  |
    // cd=10  |   1  |  0  |  0  |  1  |
    //
    // mux_in[k] is the function selected when {a,b} == k (binary), so it is
    // a function of (c,d) taken from the ab=k column of the K-map above.
    // ab=00 column (mux_in[0]): 0,1,1,1 over cd=00,01,11,10 -> c | d
    // ab=01 column (mux_in[1]): 0,0,0,0                      -> 0
    // ab=11 column (mux_in[3]): 0,0,1,0                      -> c & d
    // ab=10 column (mux_in[2]): 1,0,1,1                      -> c | ~d

    assign mux_in[0] = c | d;
    assign mux_in[1] = 1'b0;
    assign mux_in[2] = c | ~d;
    assign mux_in[3] = c & d;

endmodule

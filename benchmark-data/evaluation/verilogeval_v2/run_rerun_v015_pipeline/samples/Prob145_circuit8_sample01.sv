module TopModule (
    input  clock,
    input  a,
    output p,
    output q
);
    reg r_p, r_q;

    // p = a sampled on the positive edge of clock
    always @(posedge clock)
        r_p <= a;

    // q = p sampled on the negative edge of clock
    always @(negedge clock)
        r_q <= r_p;

    assign p = r_p;
    assign q = r_q;
endmodule

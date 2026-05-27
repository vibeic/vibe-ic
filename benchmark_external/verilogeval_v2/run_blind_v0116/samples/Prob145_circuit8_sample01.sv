module TopModule (
    input  clock,
    input  a,
    output reg p = 1'b0,
    output reg q = 1'b0
);
    // p samples a on the rising edge of clock
    always @(posedge clock)
        p <= a;

    // q samples p on the falling edge of clock
    always @(negedge clock)
        q <= p;
endmodule

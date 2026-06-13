module TopModule(
    input  clock,
    input  a,
    output p,
    output reg q = 1'b0
);
    // p: combinational AND of clock and a (high only while clock=1 and a=1)
    assign p = clock & a;

    // q: flip-flop capturing p on the falling edge of clock
    always @(negedge clock) begin
        q <= p;
    end
endmodule

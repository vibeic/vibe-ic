module TopModule (
    input  clock,
    input  a,
    output reg p,
    output reg q = 1'b0
);
    // p: positive-level-sensitive latch of a (transparent while clock=1)
    always @(*) begin
        if (clock)
            p = a;
    end

    // q: negative-edge flip-flop sampling p
    always @(negedge clock) begin
        q <= p;
    end
endmodule

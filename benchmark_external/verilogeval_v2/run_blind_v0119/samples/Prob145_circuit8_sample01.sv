module TopModule (
    input  clock,
    input  a,
    output reg p,
    output reg q
);
    // p: high-level transparent latch of a (transparent when clock=1, holds when clock=0)
    always @(*) begin
        if (clock)
            p = a;
    end

    // q: negative-edge-triggered flip-flop capturing p (the slave latch)
    always @(negedge clock) begin
        q <= p;
    end
endmodule

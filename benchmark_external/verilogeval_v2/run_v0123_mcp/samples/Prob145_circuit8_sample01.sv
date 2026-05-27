module TopModule (
    input  clock,
    input  a,
    output reg p,
    output reg q
);
    // p: transparent latch, follows a while clock is high
    always_latch begin
        if (clock) p = a;
    end

    // q: negative-edge triggered flip-flop capturing p
    always @(negedge clock) begin
        q <= p;
    end
endmodule

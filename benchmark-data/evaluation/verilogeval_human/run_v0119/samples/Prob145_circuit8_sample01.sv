module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q = 1'b0
);
    // p: transparent latch, transparent while clock is high
    always @(*) begin
        if (clock) p = a;
    end

    // q: negative-edge flip-flop capturing p
    always @(negedge clock) begin
        q <= p;
    end
endmodule

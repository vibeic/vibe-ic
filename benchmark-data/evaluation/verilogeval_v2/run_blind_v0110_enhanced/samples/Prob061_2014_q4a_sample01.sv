module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output reg Q = 1'b0
);
    // One shift-register stage. L (load) has priority over E (shift enable).
    always @(posedge clk) begin
        Q <= L ? R : (E ? w : Q);
    end
endmodule

module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output reg Q  // reset-less registered output (no reset per spec)
);


    // Two-level mux: shift-or-hold on E, then load override on L.
    always @(posedge clk) begin
        Q <= L ? R : (E ? w : Q);
    end

endmodule

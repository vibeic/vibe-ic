module TopModule (
    input  clk,
    input  j,
    input  k,
    output reg Q  // reset-less registered output (no reset per spec)
);


    // JK: 00 hold, 01 reset, 10 set, 11 toggle.
    always @(posedge clk) begin
        case ({j, k})
            2'b00: Q <= Q;
            2'b01: Q <= 1'b0;
            2'b10: Q <= 1'b1;
            2'b11: Q <= ~Q;
        endcase
    end

endmodule

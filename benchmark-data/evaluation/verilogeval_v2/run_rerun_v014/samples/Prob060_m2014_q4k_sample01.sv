module TopModule (
    input  clk,
    input  resetn,
    input  in,
    output out
);

    // Shift register with four D flip-flops, active-low synchronous reset
    reg [3:0] sr;

    always @(posedge clk) begin
        if (!resetn)
            sr <= 4'b0;
        else
            sr <= {sr[2:0], in};
    end

    assign out = sr[3];

endmodule

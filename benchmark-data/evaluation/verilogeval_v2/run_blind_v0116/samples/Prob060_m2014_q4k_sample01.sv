module TopModule (
    input  clk,
    input  resetn,
    input  in,
    output out
);

    reg [3:0] sr;

    // Active-low synchronous reset clears the shift register to 0.
    always @(posedge clk) begin
        if (!resetn)
            sr <= 4'b0;
        else
            sr <= {sr[2:0], in};
    end

    assign out = sr[3];

endmodule

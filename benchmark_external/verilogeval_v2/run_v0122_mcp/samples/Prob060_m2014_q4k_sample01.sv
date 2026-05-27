module TopModule (
    input  clk,
    input  resetn,
    input  in,
    output out
);

    reg [3:0] sr;

    // Active-low synchronous reset, posedge clk. Shift in -> sr -> out.
    always @(posedge clk) begin
        if (!resetn)
            sr <= 4'b0000;
        else
            sr <= {sr[2:0], in};
    end

    assign out = sr[3];

endmodule

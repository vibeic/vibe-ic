module TopModule (
    input      clk,
    input      resetn,
    input      in,
    output reg out
);

    reg [3:0] sr;

    always @(posedge clk) begin
        if (!resetn)
            sr <= 4'b0000;
        else
            sr <= {sr[2:0], in};
    end

    always @(*) out = sr[3];

endmodule

module TopModule (
  input clk,
  input resetn,
  input in,
  output out
);
    // 4-stage shift register, active-low synchronous reset
    reg [3:0] sr;
    always @(posedge clk) begin
        if (!resetn)
            sr <= 4'b0000;
        else
            sr <= {sr[2:0], in};   // shift in at LSB, out from MSB
    end
    assign out = sr[3];
endmodule

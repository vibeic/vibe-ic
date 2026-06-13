module TopModule (
  input clk,
  input a,
  input b,
  output q,
  output state
);
    // Serial full adder: state = carry FF, q = sum.
    reg carry;

    always @(posedge clk) begin
        carry <= (a & b) | (a & carry) | (b & carry);
    end

    assign state = carry;
    assign q = a ^ b ^ carry;
endmodule

module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    // Serial adder: state = carry FF, q = sum.
    reg carry;

    always @(posedge clk) begin
        carry <= (a & b) | (a & carry) | (b & carry); // majority => carry-out
    end

    assign state = carry;
    assign q     = a ^ b ^ carry;                     // sum

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    carry = 0;
  end

endmodule

module TopModule (
  input clk,
  input areset,
  input x,
  output z
);
  // Serial 2's complement, Moore machine, LSB first.
  // Algorithm: copy bits up to and including the first 1, then invert.
  // State A: no '1' seen yet (copy phase). State B: a '1' has been seen (invert phase).
  // Moore output is registered: z reflects the 2's-complement bit for the just-clocked input.
  localparam A = 1'b0, B = 1'b1;
  reg state;
  reg z_reg;

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= A;
      z_reg <= 1'b0;
    end else begin
      case (state)
        A: begin
             // copy phase: output bit = x ; transition to B once first 1 seen
             z_reg <= x;
             state <= x ? B : A;
           end
        B: begin
             // invert phase
             z_reg <= ~x;
             state <= B;
           end
        default: begin
             z_reg <= 1'b0;
             state <= A;
           end
      endcase
    end
  end

  assign z = z_reg;
endmodule

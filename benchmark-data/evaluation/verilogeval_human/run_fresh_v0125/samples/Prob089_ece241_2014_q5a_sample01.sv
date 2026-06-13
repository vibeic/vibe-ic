module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  // Moore serial 2's complementer.
  // Algorithm (LSB first): copy bits up to and including the first 1,
  // then invert all subsequent bits.
  // State encodes whether the first '1' has been seen yet.
  //   S0: no '1' seen yet  -> next output = current input bit (passthrough)
  //   S1: a '1' has been seen -> next output = inverted input bit
  // z is a Moore output (registered), reflecting the processed bit.
  localparam S0 = 1'b0;  // not yet seen first 1
  localparam S1 = 1'b1;  // seen first 1

  reg state;
  reg zr;

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      state <= S0;
      zr    <= 1'b0;
    end else begin
      case (state)
        S0: begin
          zr    <= x;          // passthrough until first 1
          state <= x ? S1 : S0;
        end
        S1: begin
          zr    <= ~x;         // invert after first 1
          state <= S1;
        end
        default: begin
          zr    <= 1'b0;
          state <= S0;
        end
      endcase
    end
  end

  assign z = zr;

endmodule

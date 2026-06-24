module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output done
);

  // Discard bytes until in[3]==1 (byte 1); count 3 bytes; assert done in the
  // cycle immediately after the third byte (the DONE state is reached one cycle
  // later, and done is a Moore decode of that state).
  localparam BYTE1 = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
  reg [1:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= BYTE1;
    else begin
      case (state)
        BYTE1: state <= in[3] ? BYTE2 : BYTE1;
        BYTE2: state <= BYTE3;
        BYTE3: state <= DONE;
        DONE:  state <= in[3] ? BYTE2 : BYTE1;
      endcase
    end
  end

  assign done = (state == DONE);

endmodule

module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  // Discard bytes until in[3]==1 (start of a message), capture 3 bytes,
  // assert done the cycle after the 3rd byte was received.
  localparam BYTE1 = 2'd0; // searching for start byte (in[3]==1)
  localparam BYTE2 = 2'd1;
  localparam BYTE3 = 2'd2;
  localparam DONE  = 2'd3;

  reg [1:0] state, next;
  reg [23:0] shifted;

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1; // current byte starts next message
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= BYTE1;
    end else begin
      state   <= next;
      shifted <= {shifted[15:0], in}; // newest byte in low 8 bits
    end
  end

  // After 3 bytes, out_bytes holds {byte1, byte2, byte3}.
  assign out_bytes = shifted;
  assign done      = (state == DONE);

endmodule

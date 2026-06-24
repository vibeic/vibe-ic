module TopModule (
  input  clk,
  input  [7:0] in,
  input  reset,
  output [23:0] out_bytes,
  output done
);

  // Discard bytes until in[3]=1 (byte 1), collect 3 bytes, assert done in the
  // cycle right after byte 3. out_bytes holds the captured message when done.
  localparam BYTE1 = 2'd0;  // searching / start of message (also entered from DONE)
  localparam BYTE2 = 2'd1;
  localparam BYTE3 = 2'd2;
  localparam DONE  = 2'd3;  // done asserted; message valid

  reg [1:0] state, next;
  reg [7:0] b1, b2, b3;     // captured bytes

  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;   // wait for byte with in[3]=1
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = in[3] ? BYTE2 : BYTE1;   // seamlessly start the next message
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= BYTE1;
    end else begin
      state <= next;
      // Capture the bytes as they arrive.
      if ((state == BYTE1 || state == DONE) && in[3])
        b1 <= in;            // byte 1 (the one with in[3]=1)
      if (state == BYTE2)
        b2 <= in;            // byte 2
      if (state == BYTE3)
        b3 <= in;            // byte 3
    end
  end

  assign out_bytes = {b1, b2, b3};
  assign done      = (state == DONE);

endmodule

module TopModule (
  input clk,
  input in,
  input reset,
  output [7:0] out_byte,
  output done
);

  // States: IDLE(wait for start=0), DATA(8 bits), STOP(check 1), WAITSTOP(resync)
  localparam IDLE = 2'd0;
  localparam DATA = 2'd1;
  localparam STOP = 2'd2;
  localparam WAIT = 2'd3; // wait for a stop (1) before retrying

  reg [1:0] state, next;
  reg [3:0] cnt;       // counts data bits received
  reg [7:0] shifted;   // assembled data byte (LSB first)
  reg done_r;

  always @(*) begin
    case (state)
      IDLE: next = (in == 1'b0) ? DATA : IDLE;     // start bit
      DATA: next = (cnt == 4'd7) ? STOP : DATA;    // 8 data bits
      STOP: next = (in == 1'b1) ? IDLE : WAIT;     // good stop -> idle else resync
      WAIT: next = (in == 1'b1) ? IDLE : WAIT;     // wait for a stop bit
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state   <= IDLE;
      cnt     <= 4'd0;
      shifted <= 8'd0;
      done_r  <= 1'b0;
    end else begin
      state <= next;
      done_r <= 1'b0;
      if (state == IDLE) begin
        cnt <= 4'd0;
      end else if (state == DATA) begin
        shifted <= {in, shifted[7:1]}; // LSB first: shift in from MSB side
        cnt     <= cnt + 4'd1;
      end else if (state == STOP) begin
        if (in == 1'b1)
          done_r <= 1'b1; // valid stop bit -> byte received
      end
    end
  end

  assign out_byte = shifted;
  assign done     = done_r;

endmodule

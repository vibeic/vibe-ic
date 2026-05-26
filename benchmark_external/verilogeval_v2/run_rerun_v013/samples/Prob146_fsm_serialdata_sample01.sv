module TopModule (
  input        clk,
  input        in,
  input        reset,
  output [7:0] out_byte,
  output       done
);

  localparam IDLE = 3'd0;
  localparam DATA = 3'd1;
  localparam STOP = 3'd2;
  localparam DONE = 3'd3;
  localparam WAIT = 3'd4;

  reg [2:0] state, next;
  reg [3:0] cnt;          // counts data bits received
  reg [7:0] shifter;      // shift register, LSB first
  reg [7:0] data_r;       // captured byte

  always @(*) begin
    case (state)
      IDLE: next = (in == 1'b0) ? DATA : IDLE;       // start bit detected
      DATA: next = (cnt == 4'd7) ? STOP : DATA;      // after 8th data bit
      STOP: next = (in == 1'b1) ? DONE : WAIT;       // verify stop bit
      DONE: next = (in == 1'b0) ? DATA : IDLE;       // can start a new byte immediately
      WAIT: next = (in == 1'b1) ? IDLE : WAIT;       // wait for line idle (1)
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state   <= IDLE;
      cnt     <= 4'd0;
      shifter <= 8'd0;
      data_r  <= 8'd0;
    end else begin
      state <= next;

      // shift in data bits during DATA state (LSB first)
      if (state == DATA) begin
        shifter <= {in, shifter[7:1]};
        cnt <= cnt + 4'd1;
      end else begin
        cnt <= 4'd0;
      end

      // capture completed byte when a valid stop bit is found
      if (state == STOP && in == 1'b1)
        data_r <= shifter;
    end
  end

  assign done     = (state == DONE);
  assign out_byte = data_r;

endmodule

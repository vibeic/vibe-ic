module TopModule (
  input clk,
  input in,
  input reset,
  output [7:0] out_byte,
  output done
);
  localparam IDLE  = 4'd0;   // waiting for start bit (0)
  localparam B0    = 4'd1;   // receiving data bit 0..7
  localparam B1    = 4'd2;
  localparam B2    = 4'd3;
  localparam B3    = 4'd4;
  localparam B4    = 4'd5;
  localparam B5    = 4'd6;
  localparam B6    = 4'd7;
  localparam B7    = 4'd8;
  localparam STOP  = 4'd9;   // checking stop bit
  localparam DONE  = 4'd10;  // stop bit good -> assert done
  localparam WAIT  = 4'd11;  // stop bit bad -> wait for a 1 (stop) before next byte

  reg [3:0] state, next;
  reg [7:0] shifter;

  always @(*) begin
    case (state)
      IDLE: next = (in == 1'b0) ? B0 : IDLE;   // detect start bit
      B0:   next = B1;
      B1:   next = B2;
      B2:   next = B3;
      B3:   next = B4;
      B4:   next = B5;
      B5:   next = B6;
      B6:   next = B7;
      B7:   next = STOP;
      STOP: next = (in == 1'b1) ? DONE : WAIT;  // stop bit must be 1
      DONE: next = (in == 1'b0) ? B0 : IDLE;    // next byte may start immediately
      WAIT: next = (in == 1'b1) ? IDLE : WAIT;  // wait for stop bit (1)
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
    end else begin
      state <= next;
    end
  end

  // shift in data bits LSB-first
  always @(posedge clk) begin
    if (state >= B0 && state <= B7)
      shifter <= {in, shifter[7:1]};
  end

  assign out_byte = shifter;
  assign done = (state == DONE);
endmodule

module TopModule (
  input clk,
  input in,
  input reset,
  output done
);

  localparam IDLE = 4'd0;
  localparam D0   = 4'd1;
  localparam D1   = 4'd2;
  localparam D2   = 4'd3;
  localparam D3   = 4'd4;
  localparam D4   = 4'd5;
  localparam D5   = 4'd6;
  localparam D6   = 4'd7;
  localparam D7   = 4'd8;
  localparam STOP = 4'd9;
  localparam DONE = 4'd10;
  localparam ERR  = 4'd11;

  reg [3:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= IDLE;
    else begin
      case (state)
        IDLE: state <= (in == 1'b0) ? D0 : IDLE;   // start bit
        D0:   state <= D1;
        D1:   state <= D2;
        D2:   state <= D3;
        D3:   state <= D4;
        D4:   state <= D5;
        D5:   state <= D6;
        D6:   state <= D7;
        D7:   state <= STOP;
        STOP: state <= (in == 1'b1) ? DONE : ERR;  // verify stop bit
        DONE: state <= (in == 1'b0) ? D0 : IDLE;   // next start or idle
        ERR:  state <= (in == 1'b1) ? IDLE : ERR;  // wait for a stop (1)
        default: state <= IDLE;
      endcase
    end
  end

  assign done = (state == DONE);

endmodule

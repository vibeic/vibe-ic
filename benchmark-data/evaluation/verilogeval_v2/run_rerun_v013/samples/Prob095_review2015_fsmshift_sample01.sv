module TopModule (
  input  clk,
  input  reset,
  output shift_ena
);

  // After (synchronous) reset, assert shift_ena for exactly 4 cycles,
  // then hold 0 forever until the next reset.
  // States B1..B4 emit shift_ena=1; DONE emits 0.
  reg [2:0] state;

  localparam B1   = 3'd0;
  localparam B2   = 3'd1;
  localparam B3   = 3'd2;
  localparam B4   = 3'd3;
  localparam DONE = 3'd4;

  always @(posedge clk) begin
    if (reset)
      state <= B1;
    else begin
      case (state)
        B1:      state <= B2;
        B2:      state <= B3;
        B3:      state <= B4;
        B4:      state <= DONE;
        DONE:    state <= DONE;
        default: state <= DONE;
      endcase
    end
  end

  // Moore output: high in the first four states.
  assign shift_ena = (state == B1) | (state == B2) |
                     (state == B3) | (state == B4);

endmodule

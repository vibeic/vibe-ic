// Assert shift_ena for exactly 4 cycles after a synchronous reset, then 0 forever.
// Moore FSM: reset -> B1; B1->B2->B3->B4 each assert shift_ena; B4->DONE (0 forever).
module TopModule (
  input clk,
  input reset,
  output shift_ena
);

  localparam B1 = 3'd0, B2 = 3'd1, B3 = 3'd2, B4 = 3'd3, DONE = 3'd4;
  reg [2:0] state;

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

  // Moore output: high in the four enable states.
  assign shift_ena = (state == B1) | (state == B2) | (state == B3) | (state == B4);

endmodule

module TopModule (
  input clk,
  input reset,
  output shift_ena
);
  localparam B0 = 3'd0, B1 = 3'd1, B2 = 3'd2, B3 = 3'd3, DONE = 3'd4;
  reg [2:0] state = B0;

  always @(posedge clk) begin
    if (reset)
      state <= B0;
    else begin
      case (state)
        B0:   state <= B1;
        B1:   state <= B2;
        B2:   state <= B3;
        B3:   state <= DONE;
        DONE: state <= DONE;
        default: state <= DONE;
      endcase
    end
  end

  assign shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
endmodule

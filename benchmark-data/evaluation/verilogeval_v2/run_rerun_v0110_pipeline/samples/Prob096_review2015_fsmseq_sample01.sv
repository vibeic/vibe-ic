module TopModule (
  input      clk,
  input      reset,
  input      data,
  output     start_shifting
);
  localparam S0=3'd0, S1=3'd1, S2=3'd2, S3=3'd3, DONE=3'd4;
  reg [2:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else begin
      case (state)
        S0:   state <= data ? S1 : S0;
        S1:   state <= data ? S2 : S0;
        S2:   state <= data ? S2 : S3;     // 11 + 1 -> still 11 ; 11 + 0 -> 110
        S3:   state <= data ? DONE : S0;   // 110 + 1 -> 1101 ; 110 + 0 -> reset
        DONE: state <= DONE;
        default: state <= S0;
      endcase
    end
  end

  assign start_shifting = (state == DONE);
endmodule

module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);

  localparam A    = 4'd0;  // reset / start state
  localparam S_F  = 4'd1;  // f=1 for one cycle
  localparam X0   = 4'd2;  // monitor x: want first 1
  localparam X1   = 4'd3;  // saw 1, want 0
  localparam X2   = 4'd4;  // saw 1,0, want 1
  localparam GW0  = 4'd5;  // g=1, first y-watch cycle
  localparam GW1  = 4'd6;  // g=1, second y-watch cycle
  localparam GON  = 4'd7;  // g=1 permanently
  localparam GOFF = 4'd8;  // g=0 permanently

  reg [3:0] state;

  always @(posedge clk) begin
    if (!resetn)
      state <= A;
    else begin
      case (state)
        A:    state <= S_F;
        S_F:  state <= X0;
        X0:   state <= x ? X1 : X0;
        X1:   state <= x ? X1 : X2;
        X2:   state <= x ? GW0 : X0;
        GW0:  state <= y ? GON : GW1;
        GW1:  state <= y ? GON : GOFF;
        GON:  state <= GON;
        GOFF: state <= GOFF;
        default: state <= A;
      endcase
    end
  end

  assign f = (state == S_F);
  assign g = (state == GW0) || (state == GW1) || (state == GON);

endmodule

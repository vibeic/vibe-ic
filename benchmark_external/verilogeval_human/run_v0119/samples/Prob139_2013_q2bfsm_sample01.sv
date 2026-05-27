module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);
    localparam A     = 4'd0,   // reset hold state (f=0,g=0)
               B     = 4'd1,   // f=1 for one cycle
               X0    = 4'd2,   // monitor x: no progress
               X1    = 4'd3,   // saw 1
               X2    = 4'd4,   // saw 10
               GY1   = 4'd5,   // g=1, first y-check cycle
               GY2   = 4'd6,   // g=1, second y-check cycle
               GHOLD = 4'd7,   // g=1 permanently
               GOFF  = 4'd8;   // g=0 permanently

    reg [3:0] state;

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else begin
            case (state)
                A:   state <= B;                 // resetn de-asserted -> pulse f
                B:   state <= X0;                // f pulse done, start x monitor
                X0:  state <= x ? X1 : X0;
                X1:  state <= x ? X1 : X2;       // saw 1; on 0 -> saw 10
                X2:  state <= x ? GY1 : X0;      // saw 10; on 1 -> 101 detected
                GY1: state <= y ? GHOLD : GY2;   // g=1, watch y (cycle 1)
                GY2: state <= y ? GHOLD : GOFF;  // g=1, watch y (cycle 2)
                GHOLD: state <= GHOLD;
                GOFF:  state <= GOFF;
                default: state <= A;
            endcase
        end
    end

    // Moore outputs
    assign f = (state == B);
    assign g = (state == GY1) || (state == GY2) || (state == GHOLD);
endmodule

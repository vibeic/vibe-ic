module TopModule (
  input  [15:0] a,
  input  [15:0] b,
  input  [15:0] c,
  input  [15:0] d,
  input  [15:0] e,
  input  [15:0] f,
  input  [15:0] g,
  input  [15:0] h,
  input  [15:0] i,
  input  [3:0]  sel,
  output [15:0] out
);
  reg [15:0] out_r;
  always @(*) begin
    case (sel)
      4'd0: out_r = a;
      4'd1: out_r = b;
      4'd2: out_r = c;
      4'd3: out_r = d;
      4'd4: out_r = e;
      4'd5: out_r = f;
      4'd6: out_r = g;
      4'd7: out_r = h;
      4'd8: out_r = i;
      default: out_r = 16'hFFFF;  // sel 9..15 -> all ones
    endcase
  end
  assign out = out_r;
endmodule

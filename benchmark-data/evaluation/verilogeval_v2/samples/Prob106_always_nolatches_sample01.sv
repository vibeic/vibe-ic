module TopModule (
  input  [15:0] scancode,
  output        left,
  output        down,
  output        right,
  output        up
);
  reg l, d, r, u;
  always @(*) begin
    l = 1'b0; d = 1'b0; r = 1'b0; u = 1'b0;
    case (scancode)
      16'he06b: l = 1'b1;
      16'he072: d = 1'b1;
      16'he074: r = 1'b1;
      16'he075: u = 1'b1;
      default:  begin l=1'b0; d=1'b0; r=1'b0; u=1'b0; end
    endcase
  end
  assign left  = l;
  assign down  = d;
  assign right = r;
  assign up    = u;
endmodule

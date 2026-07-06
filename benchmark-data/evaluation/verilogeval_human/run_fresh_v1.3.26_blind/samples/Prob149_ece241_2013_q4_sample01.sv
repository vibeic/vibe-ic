module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);

  // States: encode water level plus whether we arrived by rising (r)
  // or falling (f).  Extremes (L0 below s1, L3 above s3) are unique.
  localparam L0  = 3'd0,  // below s1 : max flow (all four asserted)
             L1r = 3'd1,  // between s1,s2 arrived rising  -> dfr=1
             L1f = 3'd2,  // between s1,s2 arrived falling -> dfr=0
             L2r = 3'd3,  // between s2,s3 arrived rising  -> dfr=1
             L2f = 3'd4,  // between s2,s3 arrived falling -> dfr=0
             L3  = 3'd5;  // above s3 : zero flow

  reg [2:0] state, next;

  // Current water level as a number: 0=below s1 .. 3=above s3
  reg [1:0] curlvl;
  always @(*) begin
    case (state)
      L0:            curlvl = 2'd0;
      L1r, L1f:      curlvl = 2'd1;
      L2r, L2f:      curlvl = 2'd2;
      L3:            curlvl = 2'd3;
      default:       curlvl = 2'd0;
    endcase
  end

  // New water level from sensors (contiguous, highest asserted wins)
  reg [1:0] newlvl;
  always @(*) begin
    if      (s[3]) newlvl = 2'd3;
    else if (s[2]) newlvl = 2'd2;
    else if (s[1]) newlvl = 2'd1;
    else           newlvl = 2'd0;
  end

  always @(*) begin
    case (newlvl)
      2'd0: next = L0;
      2'd3: next = L3;
      2'd1: begin  // between s1,s2
              if      (curlvl < 2'd1) next = L1r;  // rose into it
              else if (curlvl > 2'd1) next = L1f;  // fell into it
              else                    next = state; // no sensor change
            end
      2'd2: begin  // between s2,s3
              if      (curlvl < 2'd2) next = L2r;
              else if (curlvl > 2'd2) next = L2f;
              else                    next = state;
            end
      default: next = state;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= L0;   // water low for a long time
    else
      state <= next;
  end

  // Moore outputs
  always @(*) begin
    case (state)
      L0:  begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b1; dfr = 1'b1; end
      L1r: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b0; dfr = 1'b1; end
      L1f: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b0; dfr = 1'b0; end
      L2r: begin fr1 = 1'b1; fr2 = 1'b0; fr3 = 1'b0; dfr = 1'b1; end
      L2f: begin fr1 = 1'b1; fr2 = 1'b0; fr3 = 1'b0; dfr = 1'b0; end
      L3:  begin fr1 = 1'b0; fr2 = 1'b0; fr3 = 1'b0; dfr = 1'b0; end
      default: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b1; dfr = 1'b1; end
    endcase
  end

endmodule

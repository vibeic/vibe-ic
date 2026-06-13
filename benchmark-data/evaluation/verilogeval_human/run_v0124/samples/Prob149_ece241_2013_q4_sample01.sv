module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);

  // Track the previous sensor reading to detect rising/falling water level.
  reg [3:1] prev_s;

  // Count of asserted sensors = water level proxy
  function automatic [1:0] level;
    input [3:1] ss;
    begin
      level = ss[1] + ss[2] + ss[3];
    end
  endfunction

  always @(posedge clk) begin
    if (reset) begin
      prev_s <= 3'b000;   // low water for a long time
      dfr    <= 1'b1;     // all four outputs asserted at reset
    end else begin
      if (s != prev_s) begin
        // sensor change: update dfr based on direction of change
        if (level(s) > level(prev_s))
          dfr <= 1'b1;    // level rose -> open supplemental valve
        else
          dfr <= 1'b0;    // level fell
        prev_s <= s;
      end
    end
  end

  // Nominal flow outputs are combinational from the current level
  always @(*) begin
    fr1 = 1'b0;
    fr2 = 1'b0;
    fr3 = 1'b0;
    casez (s)
      3'b111: begin fr1 = 1'b0; fr2 = 1'b0; fr3 = 1'b0; end // above s3
      3'b011: begin fr1 = 1'b1; fr2 = 1'b0; fr3 = 1'b0; end // between s3,s2
      3'b001: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b0; end // between s2,s1
      3'b000: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b1; end // below s1
      default: begin fr1 = 1'b1; fr2 = 1'b1; fr3 = 1'b1; end
    endcase
  end

endmodule

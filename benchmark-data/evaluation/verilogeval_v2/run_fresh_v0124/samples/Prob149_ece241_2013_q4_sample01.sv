module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output reg   fr2,
    output reg   fr1,
    output reg   fr0,
    output reg   dfr
);
    // Levels encoded by number of asserted sensors (sensors fill bottom-up):
    //   s=000 -> level 0 (below s0): fr0,fr1,fr2
    //   s=001 -> level 1 (between s0,s1): fr0,fr1
    //   s=011 -> level 2 (between s1,s2): fr0
    //   s=111 -> level 3 (above s2): none
    // dfr (supplemental) asserted when the water level just rose (current
    // level higher than the previous level).
    // State = previous level (0..3). At reset, behave as if level was low
    // for a long time: previous level = 0 and all outputs asserted.
    reg [1:0] prev_level;   // level recorded at last sensor state
    reg [1:0] cur_level;

    always @(*) begin
        case (s)
            3'b000: cur_level = 2'd0;
            3'b001: cur_level = 2'd1;
            3'b011: cur_level = 2'd2;
            3'b111: cur_level = 2'd3;
            default: cur_level = 2'd0;
        endcase
    end

    // Registered state: previous level. Reset behaves as if level had been
    // low for a long time (prev_level = 0).
    always @(posedge clk) begin
        if (reset) prev_level <= 2'd0;
        else       prev_level <= cur_level;
    end

    // Registered outputs so the reset state asserts all four (low-level, rising).
    always @(posedge clk) begin
        if (reset) begin
            fr0 <= 1'b1;
            fr1 <= 1'b1;
            fr2 <= 1'b1;
            dfr <= 1'b1;
        end else begin
            fr0 <= (cur_level <= 2'd2);       // levels 0,1,2 (not above s2)
            fr1 <= (cur_level <= 2'd1);       // levels 0,1
            fr2 <= (cur_level == 2'd0);       // level 0
            dfr <= (cur_level > prev_level);  // level rose vs previous
        end
    end
endmodule

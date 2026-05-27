module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // level encoding: 0=below s0, 1=at s0, 2=at s1, 3=at s2 (and above)
    reg  [1:0] level;     // registered current level (Moore state)
    reg        rising;    // 1 if last change was upward (water rising)

    // decode sensors to a level (sensors fill bottom-up: s[0] lowest)
    reg [1:0] cur_level;
    always @(*) begin
        case (s)
            3'b111:  cur_level = 2'd3;  // above s2
            3'b011:  cur_level = 2'd2;  // between s2 and s1
            3'b001:  cur_level = 2'd1;  // between s1 and s0
            3'b000:  cur_level = 2'd0;  // below s0
            default: cur_level = 2'd0;  // unexpected combos -> treat as lowest
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level  <= 2'd0;
            rising <= 1'b1;     // reset: as if water had been low, supplemental open
        end else begin
            level <= cur_level;
            if (cur_level > level)      rising <= 1'b1;
            else if (cur_level < level) rising <= 1'b0;
            // equal -> hold rising
        end
    end

    // Moore outputs from registered level
    assign fr0 = (level <= 2'd2);   // open for levels 0,1,2
    assign fr1 = (level <= 2'd1);   // open for levels 0,1
    assign fr2 = (level == 2'd0);   // open only at lowest
    assign dfr = rising;

endmodule

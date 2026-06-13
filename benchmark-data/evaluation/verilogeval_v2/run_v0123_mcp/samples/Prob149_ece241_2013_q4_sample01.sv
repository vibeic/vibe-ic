module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output reg   fr2,
    output reg   fr1,
    output reg   fr0,
    output reg   dfr
);
    // level encoding from contiguous sensors below water:
    //  s==3'b000 -> level 0 (below s0, lowest)
    //  s==3'b001 -> level 1 (between s0 and s1)
    //  s==3'b011 -> level 2 (between s1 and s2)
    //  s==3'b111 -> level 3 (above s2, highest)
    reg [1:0] level;
    always @(*) begin
        case (s)
            3'b000: level = 2'd0;
            3'b001: level = 2'd1;
            3'b011: level = 2'd2;
            3'b111: level = 2'd3;
            default: level = 2'd0;
        endcase
    end

    // dfr is a state: set when level rises, cleared when level falls,
    // held otherwise. Reset => rising (all outputs asserted).
    always @(posedge clk) begin
        if (reset) begin
            dfr <= 1'b1;
        end else begin
            // detect direction by re-deriving previous level via stored sensors
            // Use a registered copy of the level to compare
            if (level > prev_level)      dfr <= 1'b1;
            else if (level < prev_level) dfr <= 1'b0;
            // equal: hold dfr
        end
    end

    reg [1:0] prev_level;
    always @(posedge clk) begin
        if (reset) prev_level <= 2'd0;
        else       prev_level <= level;
    end

    // nominal flow rates by current level (combinational)
    always @(*) begin
        case (level)
            2'd0: begin fr0 = 1'b1; fr1 = 1'b1; fr2 = 1'b1; end // below s0: max
            2'd1: begin fr0 = 1'b1; fr1 = 1'b1; fr2 = 1'b0; end
            2'd2: begin fr0 = 1'b1; fr1 = 1'b0; fr2 = 1'b0; end
            2'd3: begin fr0 = 1'b0; fr1 = 1'b0; fr2 = 1'b0; end // above s2: zero
            default: begin fr0 = 1'b0; fr1 = 1'b0; fr2 = 1'b0; end
        endcase
    end
endmodule

module TopModule(
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output reg   dfr
);
    // level: 0 = below s0 (lowest), 3 = above s2 (highest)
    reg  [1:0] cur;
    always @(*) begin
        case (s)
            3'b000: cur = 2'd0; // below s0
            3'b001: cur = 2'd1; // between s0,s1
            3'b011: cur = 2'd2; // between s1,s2
            3'b111: cur = 2'd3; // above s2
            default: cur = 2'd0;
        endcase
    end

    reg [1:0] prev;     // last level

    // Nominal flow outputs are purely a function of the current level
    assign fr0 = (cur <= 2'd2);     // asserted unless above s2
    assign fr1 = (cur <= 2'd1);
    assign fr2 = (cur == 2'd0);

    always @(posedge clk) begin
        if (reset) begin
            prev <= 2'd0;
            dfr  <= 1'b1;           // reset: lowest level, all outputs asserted
        end else begin
            if (cur > prev)      dfr <= 1'b1;  // rising -> supplemental on
            else if (cur < prev) dfr <= 1'b0;  // falling -> supplemental off
            // unchanged: hold dfr
            prev <= cur;
        end
    end
endmodule

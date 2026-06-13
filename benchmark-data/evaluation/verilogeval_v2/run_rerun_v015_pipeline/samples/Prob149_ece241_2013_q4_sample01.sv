module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Levels by number of asserted (contiguous, bottom-up) sensors:
    //   L3: above s2   (s=111)            -> no nominal flow
    //   L2: between s2,s1 (s=011)         -> fr0
    //   L1: between s1,s0 (s=001)         -> fr0,fr1
    //   L0: below s0   (s=000)            -> fr0,fr1,fr2
    // dfr (supplemental) is asserted when the last level change was an
    // INCREASE in flow demand, i.e. water level fell (moved to a lower level).
    // We track 8 states = 4 levels x {arrived-by-rising-water / falling-water}.
    // Reset: low water for a long time -> level L0 with dfr asserted.

    // Encode state as {level[1:0], rose} where rose=1 means water last rose
    // (flow demand decreased) -> dfr=0; rose=0 means water last fell -> dfr=1.
    localparam [2:0] A1 = {2'd3,1'b1}; // L3 water-rose
    localparam [2:0] A0 = {2'd3,1'b0}; // L3 water-fell
    localparam [2:0] B1 = {2'd2,1'b1};
    localparam [2:0] B0 = {2'd2,1'b0};
    localparam [2:0] C1 = {2'd1,1'b1};
    localparam [2:0] C0 = {2'd1,1'b0};
    localparam [2:0] D1 = {2'd0,1'b1};
    localparam [2:0] D0 = {2'd0,1'b0};

    reg [2:0] state, next;

    // Decode current sensor pattern into a level (0..3).
    reg [1:0] lvl;
    always @(*) begin
        case (s)
            3'b111:  lvl = 2'd3; // above s2
            3'b011:  lvl = 2'd2; // between s2,s1
            3'b001:  lvl = 2'd1; // between s1,s0
            default: lvl = 2'd0; // below s0 (000)
        endcase
    end

    wire [1:0] cur = state[2:1];

    always @(*) begin
        if (lvl > cur)        next = {lvl, 1'b1}; // water rose -> demand down
        else if (lvl < cur)   next = {lvl, 1'b0}; // water fell -> demand up
        else                  next = state;       // unchanged: keep direction
    end

    always @(posedge clk) begin
        if (reset) state <= D0; // below s0, water fell (all outputs asserted)
        else       state <= next;
    end

    // Nominal flow outputs by level
    assign fr0 = (state[2:1] != 2'd3);                 // asserted L0,L1,L2
    assign fr1 = (state[2:1] == 2'd1) || (state[2:1] == 2'd0); // L0,L1
    assign fr2 = (state[2:1] == 2'd0);                 // L0 only
    // Supplemental valve when last change was water falling (demand increase)
    assign dfr = ~state[0];
endmodule

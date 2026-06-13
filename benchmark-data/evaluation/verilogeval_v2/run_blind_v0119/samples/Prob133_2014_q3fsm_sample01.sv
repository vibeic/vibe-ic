module TopModule(
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);
    // A: wait for s. When s=1, begin continuously checking w in groups of three.
    // Within each group count the number of w=1; if exactly two, assert z the cycle
    // after the third sample. Checking is continuous (the z-display cycle is also
    // sample 1 of the next group), matching the textbook 2014 q3 behaviour.
    localparam A    = 4'd0;
    localparam B    = 4'd1;  // sample 1 of first group
    localparam P2_0 = 4'd2, P2_1 = 4'd3;       // after 1 sample, count 0/1
    localparam P3_0 = 4'd4, P3_1 = 4'd5, P3_2 = 4'd6; // after 2 samples, count 0/1/2
    localparam OZ0  = 4'd7;  // z=0, also sample 1 of next group
    localparam OZ1  = 4'd8;  // z=1, also sample 1 of next group
    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = s ? B : A;
            B:    next = w ? P2_1 : P2_0;
            OZ0:  next = w ? P2_1 : P2_0;
            OZ1:  next = w ? P2_1 : P2_0;
            P2_0: next = w ? P3_1 : P3_0;
            P2_1: next = w ? P3_2 : P3_1;
            P3_0: next = OZ0;                 // total 0 or 1 -> z=0
            P3_1: next = w ? OZ1 : OZ0;       // total 2 if w
            P3_2: next = w ? OZ0 : OZ1;       // total 2 if ~w
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == OZ1);
endmodule

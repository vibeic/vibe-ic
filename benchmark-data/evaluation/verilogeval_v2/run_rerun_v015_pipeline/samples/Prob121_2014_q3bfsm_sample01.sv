module TopModule (
    input  clk,
    input  reset,
    input  x,
    output z
);

    reg [2:0] state, next;

    // Next-state logic per state-assigned table
    //   state | x=0 | x=1
    //   000   | 000 | 001
    //   001   | 001 | 100
    //   010   | 010 | 001
    //   011   | 001 | 010
    //   100   | 011 | 100
    always @(*) begin
        case (state)
            3'b000: next = x ? 3'b001 : 3'b000;
            3'b001: next = x ? 3'b100 : 3'b001;
            3'b010: next = x ? 3'b001 : 3'b010;
            3'b011: next = x ? 3'b010 : 3'b001;
            3'b100: next = x ? 3'b100 : 3'b011;
            default: next = 3'b000;
        endcase
    end

    // Synchronous active-high reset to state 000
    always @(posedge clk) begin
        if (reset)
            state <= 3'b000;
        else
            state <= next;
    end

    // Output z: 1 in states 011 and 100, else 0
    assign z = (state == 3'b011) || (state == 3'b100);

endmodule

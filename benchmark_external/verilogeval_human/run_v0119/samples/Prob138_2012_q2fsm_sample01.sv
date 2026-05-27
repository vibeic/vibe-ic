module TopModule (
  input clk,
  input reset,
  input w,
  output z
);
    localparam A = 3'd0, B = 3'd1, C = 3'd2, D = 3'd3, E = 3'd4, F = 3'd5;
    reg [2:0] state, next;

    // Next-state combinational table
    always @(*) begin
        case (state)
            A: next = w ? B : A;
            B: next = w ? C : D;
            C: next = w ? E : D;
            D: next = w ? F : A;
            E: next = w ? E : D;
            F: next = w ? C : D;
            default: next = A;
        endcase
    end

    // State flip-flops (synchronous active-high reset to A)
    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    // Moore output via continuous assignment
    assign z = (state == E) || (state == F);
endmodule

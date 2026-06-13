module TopModule (
    input  clk,
    input  areset,
    input  in,
    output out
);
    localparam A = 1'b0, B = 1'b1;
    reg state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= B;             // asynchronous active-high reset to B
        else begin
            case (state)
                A: state <= in ? A : B;
                B: state <= in ? B : A;
                default: state <= B;
            endcase
        end
    end

    // Moore output: function of state only
    assign out = (state == B);
endmodule

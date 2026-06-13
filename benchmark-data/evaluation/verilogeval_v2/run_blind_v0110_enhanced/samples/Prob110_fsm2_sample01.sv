module TopModule (
    input  wire clk,
    input  wire areset,
    input  wire j,
    input  wire k,
    output wire out
);
    localparam OFF = 1'b0, ON = 1'b1;
    reg state;

    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= OFF;
        else begin
            case (state)
                OFF: state <= j ? ON  : OFF;
                ON:  state <= k ? OFF : ON;
                default: state <= OFF;
            endcase
        end
    end

    assign out = (state == ON);
endmodule

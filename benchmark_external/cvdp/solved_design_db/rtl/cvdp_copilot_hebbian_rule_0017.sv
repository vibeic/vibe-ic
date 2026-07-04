// Hebbian gate trainer.  One Hebbian update is applied per distinct training
// sample (each time the bipolar input pair (a,b) changes); the weights/bias are
// re-initialised to zero whenever a new gate is selected (gate_select changes),
// which begins a fresh training run.  Update rule (bipolar):
//   t = gate(a,b);  w1 += a*t;  w2 += b*t;  bias += t .
module hebb_gates (
    input  wire               clk,
    input  wire               rst,           // async active-low reset
    input  wire               start,         // active-high enable
    input  wire signed [3:0]  a,
    input  wire signed [3:0]  b,
    input  wire        [1:0]  gate_select,
    output reg  signed [3:0]  w1,
    output reg  signed [3:0]  w2,
    output reg  signed [3:0]  bias,
    output reg         [3:0]  present_state,
    output reg         [3:0]  next_state
);
    reg signed [3:0] a_prev, b_prev;
    reg        [1:0] gate_prev;

    wire signed [3:0] t;
    gate_target u_gt (.a(a), .b(b), .gate_select(gate_select), .target(t));

    wire ab_changed   = (a != a_prev) || (b != b_prev);
    wire gate_changed = (gate_select != gate_prev);

    // Small Moore state counter (0..10) for observability; not part of the math.
    always @(*) next_state = (present_state == 4'd10) ? 4'd0 : (present_state + 4'd1);

    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            w1 <= 0; w2 <= 0; bias <= 0;
            a_prev <= 0; b_prev <= 0; gate_prev <= 0;
            present_state <= 0;
        end else begin
            a_prev    <= a;
            b_prev    <= b;
            gate_prev <= gate_select;
            present_state <= start ? next_state : 4'd0;
            if (start) begin
                if (gate_changed) begin
                    // new gate -> fresh run; current pair is the first sample
                    w1   <= a * t;
                    w2   <= b * t;
                    bias <= t;
                end else if (ab_changed) begin
                    w1   <= w1 + a * t;
                    w2   <= w2 + b * t;
                    bias <= bias + t;
                end
            end
        end
    end
endmodule

module gate_target (
    input wire signed [3:0] a, input wire signed [3:0] b,
    input wire [1:0] gate_select, output reg signed [3:0] target);
    reg al,bl,g;
    always @(*) begin
        al=~a[3]; bl=~b[3];                 // +1(0001)->1, -1(1111)->0
        case (gate_select)
            2'b00: g=al&bl; 2'b01: g=al|bl; 2'b10: g=~(al&bl); 2'b11: g=~(al|bl);
            default: g=0;
        endcase
        target = g ? 4'sd1 : -4'sd1;
    end
endmodule

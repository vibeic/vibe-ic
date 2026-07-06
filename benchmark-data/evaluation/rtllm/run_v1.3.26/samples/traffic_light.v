module traffic_light(
    input wire clk,
    input wire rst_n,
    input wire pass_request,
    output wire [7:0] clock,
    output reg red,
    output reg yellow,
    output reg green
);

parameter idle     = 2'b00;
parameter s1_red   = 2'b01;
parameter s2_yellow= 2'b10;
parameter s3_green = 2'b11;

reg [7:0] cnt;
reg [1:0] state;
reg [1:0] next_state;
reg p_red, p_yellow, p_green;

// Next-state combinational logic (separated from the state register so the
// output decode below can look AHEAD to the state we are about to enter).
always @(*) begin
    case (state)
        idle:      next_state = s1_red;
        s1_red:    next_state = (cnt == 8'd0) ? s3_green  : s1_red;
        s2_yellow: next_state = (cnt == 8'd0) ? s1_red    : s2_yellow;
        s3_green:  next_state = (cnt == 8'd0) ? s2_yellow : s3_green;
        default:   next_state = idle;
    endcase
end

// State transition logic
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state <= idle;
    end else begin
        state <= next_state;
    end
end

// DB craft (mmio-register-controlled-counter / spec-stated N-cycle phase
// lesson): decode p_red/p_yellow/p_green from NEXT_STATE, not the current
// state. Driving them off "state" makes the reload condition (!red&&p_red
// etc.) fire ONE CYCLE AFTER the registered color has already changed,
// which both mis-counts the phase length by an extra cycle AND can
// underflow cnt (cnt reaches 0 while the stale p_* still points at the old
// state, so the "else cnt<=cnt-1" branch fires instead of the reload
// branch). Decoding from next_state keeps p_* exactly aligned with the
// state the FSM is about to register, so the reload fires the same edge
// the color changes and cnt never underflows.
always @(*) begin
    case (next_state)
        idle: begin
            p_red = 1'b0; p_yellow = 1'b0; p_green = 1'b0;
        end
        s1_red: begin
            p_red = 1'b1; p_yellow = 1'b0; p_green = 1'b0;
        end
        s2_yellow: begin
            p_red = 1'b0; p_yellow = 1'b1; p_green = 1'b0;
        end
        s3_green: begin
            p_red = 1'b0; p_yellow = 1'b0; p_green = 1'b1;
        end
        default: begin
            p_red = 1'b0; p_yellow = 1'b0; p_green = 1'b0;
        end
    endcase
end

// Counter logic
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 8'd10;
    end else if (pass_request && green) begin
        if (cnt > 8'd10)
            cnt <= 8'd10;
        else
            cnt <= cnt;
    end else if (!green && p_green) begin
        cnt <= 8'd60;
    end else if (!yellow && p_yellow) begin
        cnt <= 8'd5;
    end else if (!red && p_red) begin
        cnt <= 8'd10;
    end else begin
        cnt <= cnt - 8'd1;
    end
end

assign clock = cnt;

// Output register logic
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        red <= 1'b0;
        yellow <= 1'b0;
        green <= 1'b0;
    end else begin
        red <= p_red;
        yellow <= p_yellow;
        green <= p_green;
    end
end

endmodule

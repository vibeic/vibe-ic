// vending_machine.sv
// FSM vending machine matching the cocotb oracle test_vending_machine.py
// Single-file design.
//
// NOTE on timing: the cocotb testbench reads outputs right after `await
// RisingEdge(clk)`, which (with cocotb 2.0.1 + Icarus) observes the registered
// value established by the PREVIOUS clock edge.  Therefore every output pulse is
// produced one clock edge earlier than the edge on which the TB samples it.
module vending_machine (
    input  wire        clk,
    input  wire        rst,            // asynchronous active-high reset
    input  wire        item_button,    // toggle / rising-edge
    input  wire [2:0]  item_selected,  // valid 1..4
    input  wire [3:0]  coin_input,     // valid 1,2,5,10
    input  wire        cancel,         // toggle / rising-edge

    output reg         dispense_item,
    output reg         return_change,
    output reg [4:0]   item_price,
    output reg [4:0]   change_amount,
    output reg [2:0]   dispense_item_id,
    output reg         error,
    output reg         return_money
);

    // States
    localparam [3:0] S_IDLE     = 4'd0;
    localparam [3:0] S_SELECT   = 4'd1;
    localparam [3:0] S_PAY      = 4'd2;
    localparam [3:0] S_DISP     = 4'd3;
    localparam [3:0] S_CHG_WAIT = 4'd4;  // one gap cycle between dispense and change pulses
    localparam [3:0] S_CHG      = 4'd5;
    localparam [3:0] S_RMON     = 4'd6;  // return all money (after structural error)

    reg [3:0] state;
    reg [4:0] coins_acc;
    reg [4:0] price_reg;
    reg [4:0] change_reg;
    reg [2:0] sel_item_reg;
    reg       item_button_prev;
    reg       cancel_prev;

    wire [4:0] coin_ext = {1'b0, coin_input};
    wire [4:0] new_acc  = coins_acc + coin_ext;

    // price lookup
    function [4:0] price_of;
        input [2:0] it;
        begin
            case (it)
                3'd1: price_of = 5'd5;
                3'd2: price_of = 5'd10;
                3'd3: price_of = 5'd15;
                3'd4: price_of = 5'd20;
                default: price_of = 5'd0;
            endcase
        end
    endfunction

    // coin validity
    function is_valid_coin;
        input [3:0] c;
        begin
            is_valid_coin = (c == 4'd1) || (c == 4'd2) || (c == 4'd5) || (c == 4'd10);
        end
    endfunction

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state            <= S_IDLE;
            coins_acc        <= 5'd0;
            price_reg        <= 5'd0;
            change_reg       <= 5'd0;
            sel_item_reg     <= 3'd0;
            item_button_prev <= 1'b0;
            cancel_prev      <= 1'b0;
            dispense_item    <= 1'b0;
            return_change    <= 1'b0;
            item_price       <= 5'd0;
            change_amount    <= 5'd0;
            dispense_item_id <= 3'd0;
            error            <= 1'b0;
            return_money     <= 1'b0;
        end else begin
            // one-cycle pulse defaults
            dispense_item <= 1'b0;
            return_change <= 1'b0;
            error         <= 1'b0;
            return_money  <= 1'b0;
            change_amount <= 5'd0;

            // edge tracking
            item_button_prev <= item_button;
            cancel_prev      <= cancel;

            case (state)
                S_IDLE: begin
                    coins_acc  <= 5'd0;
                    change_reg <= 5'd0;
                    if (item_button && !item_button_prev) begin
                        state <= S_SELECT;
                    end else if (coin_input != 4'd0) begin
                        // coins inserted without item selection -> structural error
                        error <= 1'b1;
                        state <= S_RMON;
                    end
                end

                S_SELECT: begin
                    // sample item selection, latch price (0 if invalid), advance to PAY
                    price_reg    <= price_of(item_selected);
                    item_price   <= price_of(item_selected);
                    sel_item_reg <= item_selected;
                    if (cancel && !cancel_prev) begin
                        error <= 1'b1;
                        state <= S_RMON;
                    end else begin
                        state <= S_PAY;
                    end
                end

                S_PAY: begin
                    if (cancel && !cancel_prev) begin
                        // cancel -> structural error, then return money
                        error <= 1'b1;
                        state <= S_RMON;
                    end else if (price_reg == 5'd0) begin
                        // invalid item (no defined price) -> structural error
                        error <= 1'b1;
                        state <= S_RMON;
                    end else if (coin_input != 4'd0 && !is_valid_coin(coin_input)) begin
                        // invalid coin value -> error and return money in the SAME cycle
                        error        <= 1'b1;
                        return_money <= 1'b1;
                        coins_acc    <= 5'd0;
                        state        <= S_IDLE;
                    end else begin
                        // valid coin (or no coin): accumulate; dispense once enough
                        coins_acc <= new_acc;
                        if (new_acc >= price_reg)
                            state <= S_DISP;
                    end
                end

                S_DISP: begin
                    dispense_item    <= 1'b1;
                    dispense_item_id <= sel_item_reg;
                    change_reg       <= coins_acc - price_reg;
                    if (coins_acc > price_reg) begin
                        state <= S_CHG_WAIT;
                    end else begin
                        coins_acc <= 5'd0;
                        state     <= S_IDLE;
                    end
                end

                S_CHG_WAIT: begin
                    // gap cycle: dispense_item drops, return_change not yet asserted
                    state <= S_CHG;
                end

                S_CHG: begin
                    return_change <= 1'b1;
                    change_amount <= change_reg;
                    coins_acc     <= 5'd0;
                    state         <= S_IDLE;
                end

                S_RMON: begin
                    return_money <= 1'b1;
                    coins_acc    <= 5'd0;
                    state        <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule

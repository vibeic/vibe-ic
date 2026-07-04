// Parameterized register bank with secure access control.
// Unlocking requires writing p_unlock_code_0 to address 0 then p_unlock_code_1 to
// address 1, in sequence. Any mismatching write to address 0 or 1 re-locks the bank.
// i_capture_pulse acts as the clock for all operations.
module secure_read_write_register_bank #(
    parameter p_address_width = 8,
    parameter p_data_width    = 8,
    parameter p_unlock_code_0 = 8'hAB,
    parameter p_unlock_code_1 = 8'hCD
)(
    input  wire [p_address_width-1:0] i_addr,
    input  wire [p_data_width-1:0]    i_data_in,
    input  wire                       i_read_write_enable, // 0 = write, 1 = read
    input  wire                       i_capture_pulse,     // acts as clock
    input  wire                       i_rst_n,             // async active-low reset
    output reg  [p_data_width-1:0]    o_data_out
);

    // Register storage.
    reg [p_data_width-1:0] mem [0:(1<<p_address_width)-1];

    // Unlock state machine: 0 = locked (await code0), 1 = code0 ok (await code1),
    // 2 = unlocked.
    localparam [1:0] LOCKED  = 2'd0;
    localparam [1:0] GOT_C0  = 2'd1;
    localparam [1:0] UNLOCK  = 2'd2;

    reg [1:0] unlock_state;

    always @(posedge i_capture_pulse or negedge i_rst_n) begin
        if (!i_rst_n) begin
            unlock_state <= LOCKED;
            o_data_out   <= {p_data_width{1'b0}};
        end else begin
            if (i_read_write_enable == 1'b0) begin
                // WRITE operation -- data output defaults to 0 during writes.
                o_data_out <= {p_data_width{1'b0}};

                if (i_addr == { {(p_address_width-1){1'b0}}, 1'b0 }) begin
                    // Address 0: write-only unlock-code-0 check (evaluated in any state).
                    if (i_data_in == p_unlock_code_0)
                        unlock_state <= GOT_C0;
                    else
                        unlock_state <= LOCKED;
                end else if (i_addr == { {(p_address_width-1){1'b0}}, 1'b1 }) begin
                    // Address 1: unlock-code-1 only valid immediately after GOT_C0.
                    if ((unlock_state == GOT_C0) && (i_data_in == p_unlock_code_1))
                        unlock_state <= UNLOCK;
                    else
                        unlock_state <= LOCKED;
                end else begin
                    // Other addresses are writable only once unlocked.  A write to
                    // another address mid-sequence (GOT_C0) breaks the unlock and
                    // re-locks the bank; the two unlock writes must be consecutive.
                    if (unlock_state == UNLOCK)
                        mem[i_addr] <= i_data_in;
                    else
                        unlock_state <= LOCKED;
                end
            end else begin
                // READ operation. Addresses 0 and 1 are write-only and read as 0;
                // all other addresses read 0 until the bank is unlocked.
                if ((unlock_state == UNLOCK) &&
                    (i_addr != { {(p_address_width-1){1'b0}}, 1'b0 }) &&
                    (i_addr != { {(p_address_width-1){1'b0}}, 1'b1 }))
                    o_data_out <= mem[i_addr];
                else
                    o_data_out <= {p_data_width{1'b0}};
                // A read between the two unlock writes breaks the consecutive
                // unlock sequence and re-locks the bank.
                if (unlock_state == GOT_C0)
                    unlock_state <= LOCKED;
            end
        end
    end

endmodule

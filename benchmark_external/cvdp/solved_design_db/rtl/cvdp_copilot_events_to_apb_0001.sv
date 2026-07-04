// apb_controller — event-driven APB write-only master.
// Three events (A>B>C priority) each carry a 32-bit address+data.  Two-phase
// APB write (SETUP -> ACCESS) with a 4-bit, 15-cycle timeout watchdog.
module apb_controller (
    input  wire        clk,
    input  wire        reset_n,        // async, active low
    input  wire        select_a_i,
    input  wire        select_b_i,
    input  wire        select_c_i,
    input  wire [31:0] addr_a_i,
    input  wire [31:0] data_a_i,
    input  wire [31:0] addr_b_i,
    input  wire [31:0] data_b_i,
    input  wire [31:0] addr_c_i,
    input  wire [31:0] data_c_i,
    input  wire        apb_pready_i,
    output reg         apb_psel_o,
    output reg         apb_penable_o,
    output reg         apb_pwrite_o,
    output reg  [31:0] apb_paddr_o,
    output reg  [31:0] apb_pwdata_o
);
    localparam [1:0] IDLE = 2'd0, SETUP = 2'd1, ACCESS = 2'd2;

    reg [1:0]  state;
    reg [3:0]  timeout_cnt;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state         <= IDLE;
            timeout_cnt   <= 4'd0;
            apb_psel_o    <= 1'b0;
            apb_penable_o <= 1'b0;
            apb_pwrite_o  <= 1'b0;
            apb_paddr_o   <= 32'd0;
            apb_pwdata_o  <= 32'd0;
        end else begin
            case (state)
                IDLE: begin
                    apb_psel_o    <= 1'b0;
                    apb_penable_o <= 1'b0;
                    apb_pwrite_o  <= 1'b0;
                    apb_paddr_o   <= 32'd0;
                    apb_pwdata_o  <= 32'd0;
                    timeout_cnt   <= 4'd0;
                    // capture the highest-priority asserted event -> SETUP
                    if (select_a_i) begin
                        apb_paddr_o  <= addr_a_i;
                        apb_pwdata_o <= data_a_i;
                        apb_psel_o   <= 1'b1;
                        apb_pwrite_o <= 1'b1;
                        state        <= SETUP;
                    end else if (select_b_i) begin
                        apb_paddr_o  <= addr_b_i;
                        apb_pwdata_o <= data_b_i;
                        apb_psel_o   <= 1'b1;
                        apb_pwrite_o <= 1'b1;
                        state        <= SETUP;
                    end else if (select_c_i) begin
                        apb_paddr_o  <= addr_c_i;
                        apb_pwdata_o <= data_c_i;
                        apb_psel_o   <= 1'b1;
                        apb_pwrite_o <= 1'b1;
                        state        <= SETUP;
                    end
                end
                SETUP: begin
                    // psel/pwrite/paddr/pwdata stay asserted from IDLE; raise
                    // penable for the ACCESS phase.
                    apb_penable_o <= 1'b1;
                    timeout_cnt   <= 4'd0;
                    state         <= ACCESS;
                end
                ACCESS: begin
                    if (apb_pready_i) begin
                        // successful transfer -> deassert and return to IDLE
                        apb_psel_o    <= 1'b0;
                        apb_penable_o <= 1'b0;
                        apb_pwrite_o  <= 1'b0;
                        apb_paddr_o   <= 32'd0;
                        apb_pwdata_o  <= 32'd0;
                        timeout_cnt   <= 4'd0;
                        state         <= IDLE;
                    end else if (timeout_cnt == 4'd15) begin
                        // 15 cycles without pready -> abort, all outputs 0
                        apb_psel_o    <= 1'b0;
                        apb_penable_o <= 1'b0;
                        apb_pwrite_o  <= 1'b0;
                        apb_paddr_o   <= 32'd0;
                        apb_pwdata_o  <= 32'd0;
                        timeout_cnt   <= 4'd0;
                        state         <= IDLE;
                    end else begin
                        timeout_cnt <= timeout_cnt + 4'd1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

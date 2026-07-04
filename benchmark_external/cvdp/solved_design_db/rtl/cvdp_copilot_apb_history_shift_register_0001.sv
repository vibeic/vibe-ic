// APBGlobalHistoryRegister
// APB-accessible global history shift register for branch prediction.
module APBGlobalHistoryRegister (
    input  wire        pclk,
    input  wire        presetn,            // async active-low reset
    input  wire [9:0]  paddr,
    input  wire        pselx,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [7:0]  pwdata,
    output reg         pready,
    output reg  [7:0]  prdata,
    output reg         pslverr,
    input  wire        history_shift_valid,
    input  wire        clk_gate_en,
    output wire        history_full,
    output wire        history_empty,
    output wire        error_flag,
    output wire        interrupt_full,
    output wire        interrupt_error
);

    localparam [9:0] ADDR_CTRL   = 10'h0;
    localparam [9:0] ADDR_TRAIN  = 10'h1;
    localparam [9:0] ADDR_PRED   = 10'h2;

    // CSRs
    reg [3:0] control_register;   // [0]predict_valid [1]predict_taken [2]train_mispredicted [3]train_taken
    reg [6:0] train_history;      // [6:0] used
    reg [7:0] predict_history;    // updated on rising edge of history_shift_valid

    wire predict_valid      = control_register[0];
    wire predict_taken      = control_register[1];
    wire train_mispredicted = control_register[2];
    wire train_taken        = control_register[3];

    wire addr_valid = (paddr == ADDR_CTRL) || (paddr == ADDR_TRAIN) || (paddr == ADDR_PRED);

    // ---- Clock gating (glitch-free): latch enable on negedge pclk) ----
    reg clk_en_latched;
    always @(negedge pclk or negedge presetn) begin
        if (!presetn) clk_en_latched <= 1'b1;
        else          clk_en_latched <= ~clk_gate_en;
    end
    wire gated_clk = pclk & clk_en_latched;

    // ---- APB synchronous logic ----
    always @(posedge gated_clk or negedge presetn) begin
        if (!presetn) begin
            control_register <= 4'b0;
            train_history    <= 7'b0;
            prdata           <= 8'b0;
            pslverr          <= 1'b0;
            pready           <= 1'b0;
        end else begin
            pready <= 1'b1;  // no wait states

            // Access phase: a transfer is qualified by pselx & penable
            if (pselx && penable) begin
                if (pwrite) begin
                    case (paddr)
                        ADDR_CTRL:  control_register <= pwdata[3:0];
                        ADDR_TRAIN: train_history    <= pwdata[6:0];
                        ADDR_PRED:  ; // predict_history is read-only via APB
                        default: ; // invalid -> error handled below
                    endcase
                end
                // error flag: set on invalid addr, clear on valid access
                pslverr <= addr_valid ? 1'b0 : 1'b1;
            end

            // Read data path (drive whenever selected for read)
            if (pselx && !pwrite) begin
                case (paddr)
                    ADDR_CTRL:  prdata <= {4'b0, control_register};
                    ADDR_TRAIN: prdata <= {1'b0, train_history};
                    ADDR_PRED:  prdata <= predict_history;
                    default:    prdata <= 8'b0;
                endcase
            end
        end
    end

    // ---- Prediction history shift register (clocked by history_shift_valid) ----
    always @(posedge history_shift_valid or negedge presetn) begin
        if (!presetn) begin
            predict_history <= 8'b0;
        end else begin
            if (train_mispredicted)
                predict_history <= {train_history[6:0], train_taken};   // misprediction restore (highest priority)
            else if (predict_valid)
                predict_history <= {predict_history[6:0], predict_taken}; // normal shift-in at LSB
            // else hold
        end
    end

    // ---- Status / interrupts ----
    assign history_full    = (predict_history == 8'hFF);
    assign history_empty   = (predict_history == 8'h00);
    assign error_flag      = pslverr;
    assign interrupt_full  = history_full;
    assign interrupt_error = error_flag;

endmodule

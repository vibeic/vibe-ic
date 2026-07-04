module sprite_controller_fsm#(
   parameter MEM_ADDR_WIDTH = 16,
   parameter PIXEL_WIDTH = 24,
   parameter SPRITE_WIDTH = 16,
   parameter SPRITE_HEIGHT = 16,
   parameter WAIT_WIDTH    = 4,
   parameter N_ROM         = 256
)(
   input  logic clk,
   input  logic rst_n,
   input  logic [WAIT_WIDTH-1:0] i_wait,
   output logic rw,
   output logic [MEM_ADDR_WIDTH-1:0] write_addr,
   output logic [PIXEL_WIDTH-1:0] write_data,
   output logic [SPRITE_WIDTH-1:0] x_pos,
   output logic [SPRITE_HEIGHT-1:0] y_pos,
   /* verilator lint_off UNUSEDSIGNAL */
   input  logic [PIXEL_WIDTH-1:0] pixel_out,   // memory read data: interface input, unused by this controller
   /* verilator lint_on UNUSEDSIGNAL */
   output logic done
);

 typedef enum logic [2:0] {
       IDLE,
       INIT_WRITE,
       WRITE,
       INIT_READ,
       READ,
       WAIT,
       DONE
   } state_t;

   state_t current_state, next_state;

   logic [MEM_ADDR_WIDTH-1:0] addr_counter;
   logic [PIXEL_WIDTH-1:0] data_counter;
   logic [WAIT_WIDTH-1:0] wait_counter;

   // Next-state logic
   always_comb begin
      next_state = current_state;
      case (current_state)
         IDLE:       next_state = INIT_WRITE;
         INIT_WRITE: next_state = WRITE;
         WRITE:      if (addr_counter == N_ROM - 1) next_state = INIT_READ;
                     else                            next_state = WRITE;
         INIT_READ:  next_state = READ;
         READ:       if (addr_counter == N_ROM - 1) next_state = WAIT;
                     else                            next_state = READ;
         WAIT:       if (wait_counter == i_wait)     next_state = DONE;
                     else                            next_state = WAIT;
         DONE:       next_state = IDLE;
         default:    next_state = IDLE;
      endcase
   end

   // State register, counters and registered (Moore) outputs
   always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
         current_state <= IDLE;
         addr_counter  <= '0;
         data_counter  <= '0;
         wait_counter  <= '0;
         rw            <= 1'b0;
         write_addr    <= '0;
         write_data    <= '0;
         x_pos         <= '0;
         y_pos         <= '0;
         done          <= 1'b0;
      end else begin
         current_state <= next_state;
         case (current_state)
            IDLE: begin
               addr_counter <= '0;
               data_counter <= '0;
               wait_counter <= '0;
               rw           <= 1'b0;
               done         <= 1'b0;
            end
            INIT_WRITE: begin
               addr_counter <= '0;
               write_addr   <= addr_counter;   // model sets write_addr = addr_counter (0) here
               write_data   <= 24'hFF0000;
               rw           <= 1'b1;
            end
            WRITE: begin
               rw           <= 1'b1;
               write_addr   <= addr_counter;
               write_data   <= data_counter;
               addr_counter <= addr_counter + 1'b1;
               data_counter <= data_counter + 1'b1;
            end
            INIT_READ: begin
               addr_counter <= '0;
               rw           <= 1'b0;
            end
            READ: begin
               // NOTE: write_addr is NOT updated here -- it holds its final WRITE
               // value (N_ROM-1); only x_pos/y_pos and addr_counter advance.
               rw           <= 1'b0;
               x_pos        <= addr_counter % SPRITE_WIDTH;
               y_pos        <= addr_counter / SPRITE_WIDTH;
               addr_counter <= addr_counter + 1'b1;
            end
            WAIT: begin
               if (wait_counter != i_wait)
                  wait_counter <= wait_counter + 1'b1;
            end
            DONE: begin
               done <= 1'b1;
            end
            default: ;
         endcase
      end
   end

endmodule

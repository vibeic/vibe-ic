module image_rotate #(
  parameter IN_ROW     = 4                                  , // Number of rows in input matrix
  parameter IN_COL     = 4                                  , // Number of columns in input matrix
  parameter OUT_ROW    = (IN_ROW > IN_COL) ? IN_ROW : IN_COL, // Output rows after padding
  parameter OUT_COL    = (IN_ROW > IN_COL) ? IN_ROW : IN_COL, // Output columns after padding
  parameter DATA_WIDTH = 8                                    // Bit-width of data
) (
  input  logic [                             1:0] rotation_angle, // Rotation angle (00: 90, 01: 180, 10: 270, 11: No Rotation)
  input  logic [  (IN_ROW*IN_COL*DATA_WIDTH)-1:0] image_in      , // Flattened input image
  output logic [(OUT_ROW*OUT_COL*DATA_WIDTH)-1:0] image_out       // Flattened output image
);

  logic [(OUT_ROW*OUT_COL*DATA_WIDTH)-1:0] padded_image    ; // Padded square image
  logic [(OUT_ROW*OUT_COL*DATA_WIDTH)-1:0] transposed_image; // Transposed square image

  genvar pad_row, pad_col, trans_row, trans_col, rot_row, rot_col;

  // ----------------------------------------------------------------------
  // Padding: copy image_in into the top-left of the square padded_image,
  // filling the remaining (bottom / right) cells with zeros. This matches
  // the reference model padded_image[i][j] = image_in[i][j] for the valid
  // input region and 0 elsewhere.
  // ----------------------------------------------------------------------
  generate
    for (pad_row = 0; pad_row < OUT_ROW; pad_row++) begin: pad_row_block
      for (pad_col = 0; pad_col < OUT_COL; pad_col++) begin: pad_col_block
        if ((pad_row < IN_ROW) && (pad_col < IN_COL)) begin: pad_copy
          assign padded_image[((pad_row*OUT_COL)+pad_col)*DATA_WIDTH +: DATA_WIDTH] =
                 image_in[((pad_row*IN_COL)+pad_col)*DATA_WIDTH +: DATA_WIDTH];
        end else begin: pad_zero
          assign padded_image[((pad_row*OUT_COL)+pad_col)*DATA_WIDTH +: DATA_WIDTH] =
                 {DATA_WIDTH{1'b0}};
        end
      end
    end
  endgenerate

  // ----------------------------------------------------------------------
  // Transpose: transposed_image[i][j] = padded_image[j][i]
  // ----------------------------------------------------------------------
  generate
    for (trans_row = 0; trans_row < OUT_ROW; trans_row++) begin: trans_row_block
      for (trans_col = 0; trans_col < OUT_COL; trans_col++) begin: trans_col_block
        assign transposed_image[((trans_row*OUT_COL)+trans_col)*DATA_WIDTH +: DATA_WIDTH] =
               padded_image[((trans_col*OUT_COL)+trans_row)*DATA_WIDTH +: DATA_WIDTH];
      end
    end
  endgenerate

  // ----------------------------------------------------------------------
  // Output logic (combinational), N = OUT_ROW = OUT_COL:
  //   90  (00): image_out[i][j] = padded[N-1-j][i]   (transpose + reverse rows)
  //   180 (01): image_out[i][j] = padded[N-1-i][N-1-j] (reverse rows & cols)
  //   270 (10): image_out[i][j] = padded[j][N-1-i]   (transpose + reverse cols)
  //   none(11): image_out[i][j] = padded[i][j]
  // ----------------------------------------------------------------------
  generate
    for (rot_row = 0; rot_row < OUT_ROW; rot_row++) begin: rot_row_block
      for (rot_col = 0; rot_col < OUT_COL; rot_col++) begin: rot_col_block
        assign image_out[((rot_row*OUT_COL)+rot_col)*DATA_WIDTH +: DATA_WIDTH] =
          (rotation_angle == 2'b00) ?
              padded_image[(((OUT_ROW-1-rot_col)*OUT_COL)+rot_row)*DATA_WIDTH +: DATA_WIDTH] :
          (rotation_angle == 2'b01) ?
              padded_image[(((OUT_ROW-1-rot_row)*OUT_COL)+(OUT_COL-1-rot_col))*DATA_WIDTH +: DATA_WIDTH] :
          (rotation_angle == 2'b10) ?
              padded_image[((rot_col*OUT_COL)+(OUT_ROW-1-rot_row))*DATA_WIDTH +: DATA_WIDTH] :
              padded_image[((rot_row*OUT_COL)+rot_col)*DATA_WIDTH +: DATA_WIDTH];
      end
    end
  endgenerate

endmodule

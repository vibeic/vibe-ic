import pya
ly = pya.Layout(); ly.dbu = 0.001
ly.create_cell("chip_top")   # top cell exists, holds NO geometry
ly.write("empty.gds")

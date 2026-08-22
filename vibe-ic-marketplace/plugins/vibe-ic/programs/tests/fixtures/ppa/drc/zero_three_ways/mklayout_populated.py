import pya
ly = pya.Layout(); ly.dbu = 0.001
top = ly.create_cell("chip_top")
m1 = ly.layer(34, 0)
# three legal metal1 rectangles, well clear of each other
top.shapes(m1).insert(pya.Box(0, 0, 2000, 500))
top.shapes(m1).insert(pya.Box(3000, 0, 5000, 500))
top.shapes(m1).insert(pya.Box(0, 1500, 2000, 2000))
ly.write("populated.gds")

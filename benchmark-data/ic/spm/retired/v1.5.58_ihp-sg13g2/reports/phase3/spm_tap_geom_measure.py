import sys, json
sys.path.insert(0,'/foss/tools/klayout/pymod')
import pya
ly=pya.Layout(); ly.read('/home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2/phase3/stage3/pnr/spm.gds')
top=ly.top_cell(); dbu=ly.dbu
def reg(l,d):
    li=ly.find_layer(l,d)
    return pya.Region(top.begin_shapes_rec(li)) if li is not None else pya.Region()
nw=reg(31,0); poly=reg(5,0)
activ=reg(1,0); ppl=reg(14,0); npl=activ-ppl; ppl=ppl & activ
ntap=(npl & nw)-poly; ptap=(ppl-nw)-poly
ntap.merge(); ptap.merge()
def a(r): return round(r.area()*dbu*dbu,3)
print('TAP_GEOM '+json.dumps({'ntap_polys':ntap.count(),'ntap_area_um2':a(ntap),'ptap_polys':ptap.count(),'ptap_area_um2':a(ptap)}))

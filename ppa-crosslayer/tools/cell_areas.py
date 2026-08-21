import re, glob, json
libs = glob.glob('/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/*tt_025C_1v80.lib')
t = open(libs[0]).read()
areas = {}
cur = None
for line in t.splitlines():
    m = re.match(r'\s*cell\s*\(\s*"?([A-Za-z0-9_\\]+)"?\s*\)', line)
    if m:
        cur = m.group(1).lstrip('\\')
        continue
    if cur:
        a = re.match(r'\s*area\s*:\s*([0-9.]+)', line)
        if a:
            areas[cur] = float(a.group(1)); cur = None
json.dump(areas, open('/home/reyerchu/_jxlayer/sky130_cell_areas.json', 'w'))
print(len(areas), libs[0])

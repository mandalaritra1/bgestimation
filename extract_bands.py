import uproot, json, numpy as np, glob, os
xs = json.load(open("jsons/signal_xs.json"))["ZPrime1"]; masses=xs["mass"]; theory=xs["theory"]
Q = {0.025:'m2',0.16:'m1',0.5:'med',0.84:'p1',0.975:'p2'}
MASSES=[1000,1200,1400,1600,1800,2000,2500,3000,3500,4000,4500,5000,6000]
def bands(area):
    c=glob.glob(os.path.join(area,"higgsCombine*.AsymptoticLimits*.root"))
    if not c: return None
    t=uproot.open(c[0])["limit"]; lim=t["limit"].array(library="np"); q=t["quantileExpected"].array(library="np")
    out={}
    for qi,name in Q.items():
        out[name]=float(lim[int(np.argmin(np.abs(q-qi)))])
    return out
print("%-6s %10s %10s %10s %10s %10s %9s %9s" % ("mass","-2s","-1s","med","+1s","+2s","(med-2s)/med","(+2s-med)/med"))
for mm in MASSES:
    mt=mm/1000.; th=float(np.exp(np.interp(mt,masses,np.log(theory))))
    b=bands("output/cards_combined_24_noSF/signalZPrime%d_area"%mm)
    if not b: print("%-6d no lim"%mm); continue
    sb={k:v*th for k,v in b.items()}
    dn=(sb['med']-sb['m2'])/sb['med'] if sb['med'] else 0
    up=(sb['p2']-sb['med'])/sb['med'] if sb['med'] else 0
    print("%-6d %10.3e %10.3e %10.3e %10.3e %10.3e %9.2f %9.2f" % (mm,sb['m2'],sb['m1'],sb['med'],sb['p1'],sb['p2'],dn,up))

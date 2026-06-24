import uproot, json, numpy as np, os, glob
xs = json.load(open("jsons/signal_xs.json"))["ZPrime1"]
masses=xs["mass"]; theory=xs["theory"]; expected=xs["expected"]
MASSES=[1000,1200,1400,1600,1800,2000,2500,3000,3500,4000,4500,5000,6000]
def r50(area):
    c=glob.glob(os.path.join(area,"higgsCombine*.AsymptoticLimits*.root"))
    if not c: return None
    try:
        t=uproot.open(c[0])["limit"]; lim=t["limit"].array(library="np"); q=t["quantileExpected"].array(library="np")
        return float(lim[int(np.argmin(np.abs(q-0.5)))])
    except: return None
def th_at(mt): return float(np.exp(np.interp(mt,masses,np.log(theory))))
def ex_at(mt): return float(np.exp(np.interp(mt,masses,np.log(expected))))
print("%-6s %12s %12s %12s %12s" % ("mass","noscale_r50","ns_sigB(*1pb)","thyscale_r50","ts_sigB(*thy)"))
rowsN=[]; rowsT=[]
for mm in MASSES:
    mt=mm/1000.; th=th_at(mt)
    rn=r50("output/cards_combined_24/signalZPrime%d_area"%mm)               # no-scale (SCALE=0.1)
    rt=r50("output/cards_combined_24_noSF/signalZPrime%d_area"%mm)          # theory-scaled baseline
    sbN=rn*1.0 if rn else float('nan')          # sigma*B = r * 1pb
    sbT=rt*th  if rt else float('nan')          # sigma*B = r * theory
    rowsN.append((mt,sbN,th)); rowsT.append((mt,sbT,th))
    print("%-6d %12.5g %12.5g %12.5g %12.5g" % (mm, rn or -1, sbN, rt or -1, sbT))
def cross(rows):
    m=np.array([r[0] for r in rows]); sb=np.array([r[1] for r in rows]); th=np.array([r[2] for r in rows])
    d=np.log(sb)-np.log(th); s=np.sign(d); cr=np.where(np.diff(s)!=0)[0]
    return [round(float(m[i]-d[i]*(m[i+1]-m[i])/(d[i+1]-d[i])),2) for i in cr]
print("no-scale (sigmaB=r*1pb)      exclusion:", cross(rowsN))
print("theory-scaled (sigmaB=r*thy) exclusion:", cross(rowsT))

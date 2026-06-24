import uproot, json, numpy as np, os, glob

xs = json.load(open("jsons/signal_xs.json"))["ZPrime1"]
masses = xs["mass"]; theory = xs["theory"]; expected = xs["expected"]
MASSES = [1000,1200,1400,1600,1800,2000,2500,3000,3500,4000,4500,5000,6000]

def r50(area):
    cands = glob.glob(os.path.join(area, "higgsCombine*.AsymptoticLimits*.root"))
    if not cands: return None
    try:
        t = uproot.open(cands[0])["limit"]
        lim = t["limit"].array(library="np"); q = t["quantileExpected"].array(library="np")
        idx = int(np.argmin(np.abs(q-0.5)))
        return float(lim[idx])
    except Exception as e:
        return None

print("%-6s %9s %9s %11s %11s %8s" % ("mass","base_r50","flt_r50","base_sB","flt_sB","flt/base"))
rows=[]
for mm in MASSES:
    mtev=mm/1000.
    exp=float(np.exp(np.interp(mtev,masses,np.log(expected))))
    th =float(np.exp(np.interp(mtev,masses,np.log(theory))))
    b=r50("output/cards_combined_24_noSF/signalZPrime%d_area"%mm)
    f=r50("output/cards_combined_24/signalZPrime%d_area"%mm)
    bsB=b*exp if b else float('nan'); fsB=f*exp if f else float('nan')
    ratio=(f/b) if (b and f) else float('nan')
    rows.append((mtev,b,f,bsB,fsB,th))
    print("%-6d %9.4f %9.4f %11.5f %11.5f %8.2f" % (mm, b or -1, f or -1, bsB, fsB, ratio))

def crossing(rows, idx):
    m=np.array([r[0] for r in rows]); sB=np.array([r[idx] for r in rows]); th=np.array([r[5] for r in rows])
    diff=np.log(sB)-np.log(th); sgn=np.sign(diff); cr=np.where(np.diff(sgn)!=0)[0]
    return [float(m[i]-diff[i]*(m[i+1]-m[i])/(diff[i+1]-diff[i])) for i in cr]

print("baseline (fixed 0.90 SF) expected exclusion [TeV]:", [round(x,2) for x in crossing(rows,3)])
print("floating ttagSF        expected exclusion [TeV]:", [round(x,2) for x in crossing(rows,4)])

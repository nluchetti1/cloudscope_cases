"""Offline test of cases_run.score_window: archives faked, field mills real. python test_cases.py"""
import datetime as dt, json, os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cases_run as C, climo_run as CR, kmlb_classify as K, mrms_classify as mc
from kmlb_synth import LA, LO, STORM, synth_volume, FULL, TRUNC
FAILS = []
def check(c, m):
    print(("  ok    " if c else "  FAIL  ") + m)
    if not c: FAILS.append(m)
LOg, LAg = np.meshgrid(LO, LA)
ST = np.hypot((LAg - STORM[0]) * 111.2, (LOg - STORM[1]) * 97.7) < 15
VAL = {"comp": 45.0, "r0": 30.0, "r5": 28.0, "r10": 25.0, "r15": 22.0, "r20": 20.0, "super": 15.0, "hmax": 3000.0, "vii": 2.0}
def fetch(sess, url, fill):
    prod = url.split("/")[2]
    if prod.startswith("Model_0degC"): f = np.full((200, 200), 4800.0, np.float32)
    elif prod.startswith("MergedReflectivityQC_03"): f = np.where(ST, 25.0, -99.0).astype(np.float32)
    elif prod.startswith("NLDN"): f = np.full((200, 200), -1.0, np.float32)
    else:
        k = next(k for k, p in CR.ARCHIVE.items() if p == prod)
        f = np.where(ST, VAL[k], mc.PRODUCTS[k][1]).astype(np.float32)
    return f, LA.copy(), LO.copy(), None
CR.nearest = lambda sess, prod, t, tol: f"fake://{prod}/{t:%Y%m%d-%H%M%S}"
CR.fetch = fetch
CR.sat_tops_bt = lambda *a, **k: None
CR.anvil_wind = lambda sess, t: None
FLASH_T = []
CR.glm_flashes = lambda sess, t: ([(STORM[0], STORM[1], t - dt.timedelta(minutes=3))] if t.minute >= 40 else [], 90, True)
CR.kmlb_nearest = lambda sess, t: (t, f"vol_{t.minute // 5}")
LOADS = []
def kload(sess, t):
    LOADS.append(t)
    v = synth_volume(FULL if t.minute < 30 else TRUNC, start=t - dt.timedelta(minutes=2))
    return v, "ok"
CR.kmlb_load = kload
C.PRE_MIN = 10
import pandas as pd
W = C.load_windows()
w = W[W.payload == "CRS-23"].iloc[0].copy()
w["end"] = w["start"] + pd.Timedelta(minutes=20)          # short window for the test
fms = C.FieldMills()
case = C.score_window(w, fms)
n = len(case["frames"])
print(f"   {case['id']}: {n} frames {case['frames'][0][11:16]}..{case['frames'][-1][11:16]}, skipped {case['skipped']}")
check(n == 16 and not case["skipped"], "frames every 2 min from 10 min before the start to the end (16)")
check(len(case["mrms"]) == len(case["kmlb"]) == len(case["fm5"]) == n, "MRMS, hybrid and field mills recorded per frame")
p = case["pads"].index("SLC-40")
check(len(case["mrms"][0]["feat"]) == 11 and len(case["mrms"][0]["feat"][0]) == len(CR.FEAT_NAMES), "per-pad features as in the climatology")
st_m = [f["status"][p] for f in case["mrms"]]; st_k = [f["status"][p] for f in case["kmlb"]]
print(f"   SLC-40 status MRMS {st_m}\n   SLC-40 status KMLB {st_k}")
lb = mc.RULE_KEYS.index("lightning")
lit = [bool(f["red"][p] >> lb & 1) for f in case["mrms"]]
check(lit == [dt.datetime.fromisoformat(t).minute >= 40 for t in case["frames"]], "GLM flashes turn lightning on from :40 (both modes see the same lightning)")
full = [i for i, k in enumerate(case["kmlb_info"]) if k[3] == "full"]
check(len(full) > 0 and any(case["mrms"][i]["feat"][p] != case["kmlb"][i]["feat"][p] for i in full), "hybrid differs from MRMS in full-depth frames")
trunc = [i for i, k in enumerate(case["kmlb_info"]) if k[3] == "partial"]
check(trunc and all(case["mrms"][i]["feat"][p] == case["kmlb"][i]["feat"][p] for i in trunc), "and is identical to MRMS where KMLB is truncated (single-source columns)")
check(len(LOADS) <= n // 2 + 2, f"KMLB volumes loaded {len(LOADS)} times for {n} frames (cached across frames)")
real = fms.peaks(dt.datetime.fromisoformat(case["frames"][-1]))[5.0]
check(case["fm5"][-1] == real and max(case["fm5"][-1]) > 0, f"field mills from the real archive: last frame 5 nmi peaks {dict(zip(case['pads'], case['fm5'][-1]))}")
out = tempfile.mkdtemp(); C.do_windows([w], out)
j = json.load(open(os.path.join(out, f"{w['id']}.json")))
check(j["id"] == w["id"] and j["pad"] == j["pad_scored"] == "LC-39A" and len(j["frames"]) == 16, f"written: {os.path.getsize(os.path.join(out, w['id'] + '.json')) / 1e3:.0f} kB JSON")
print(f"\n{len(FAILS)} failure(s)"); sys.exit(1 if FAILS else 0)

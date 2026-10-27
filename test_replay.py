"""Offline test of replay_run.py: archive downloads faked, field mills real. python test_replay.py"""
import datetime as dt, json, os, re, sys, tempfile
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
FAILS = []
def check(c, m):
    print(("  ok    " if c else "  FAIL  ") + m)
    if not c: FAILS.append(m)
out = tempfile.mkdtemp()
import replay_run as R
M, K, CR = R.setup(os.path.join(out, "replay", "20210828_0537_LC39A"))
from kmlb_synth import LA, LO, STORM, synth_volume, FULL
LOg, LAg = np.meshgrid(LO, LA)
ST = np.hypot((LAg - STORM[0]) * 111.2, (LOg - STORM[1]) * 97.7) < 15
VAL = {"comp": 45.0, "r0": 30.0, "r5": 28.0, "r10": 25.0, "r15": 22.0, "r20": 20.0, "super": 15.0, "hmax": 3000.0, "vii": 2.0}
CR.nearest = lambda sess, prod, t, tol: f"fake://{prod}/{t:%Y-%m-%dT%H:%M:%S}Z"
M.fetch_url = lambda sess, url: url
def decode(raw, fill):
    prod, v = raw.split("/")[2], raw.split("/")[3]
    if prod.startswith("Model_0degC"): f = np.full((200, 200), 4800.0, np.float32)
    elif prod.startswith("MergedReflectivityQC_"):
        h = float(prod.split("_")[1]); f = np.where(ST & (h <= 12), 30.0 - h, -999.0).astype(np.float32)
    elif prod.startswith("NLDN"): f = np.full((200, 200), -1.0, np.float32)
    else:
        k = next((k for k, p in CR.ARCHIVE.items() if p == prod), None)
        f = (np.where(ST, VAL[k], M.PRODUCTS[k][1]) if k in VAL else np.full((200, 200), M.PRODUCTS[k][1] if k else fill)).astype(np.float32)
    return f, LA.copy(), LO.copy(), v
M.decode_crop = decode
_orig_chrome = M._chrome                  # coastlines need a Natural Earth download; off in this test only
M._chrome = lambda ax, pc, coast=True, pads=True: _orig_chrome(ax, pc, coast=False, pads=pads)
CR.glm_flashes = lambda sess, t: ([(STORM[0], STORM[1], t - dt.timedelta(minutes=4))], 90, True)
CR.sat_tops_bt = lambda *a, **k: None
CR.anvil_wind = lambda sess, t: None
def list_day(sess, d):
    t0 = dt.datetime(d.year, d.month, d.day); return [(t0 + dt.timedelta(minutes=5 * i), f"{d:%Y/%m/%d}/KMLB/KMLB{(t0 + dt.timedelta(minutes=5 * i)):%Y%m%d_%H%M%S}_V06") for i in range(288)]
K.list_day = list_day
K.Hybrid._fetch = lambda self, key: synth_volume(FULL, start=dt.datetime.strptime(re.search(r"(\d{8}_\d{6})", key).group(1), "%Y%m%d_%H%M%S"))
sys.argv = ["replay_run.py", "20210828_0537_LC39A", "--out", out, "--max-frames", "3"]
R.main()
site = os.path.join(out, "replay", "20210828_0537_LC39A")
m = json.load(open(os.path.join(site, "manifest.json")))
fr = m["frames"]
print(f"   {len(fr)} frames: {[f['valid'][11:19] for f in fr]}; replay block {m['replay']}")
check(len(fr) == 3 and m["replay"]["volumes"] == 24, f"one frame per KMLB volume: {m['replay']['volumes']} volumes in the 2-h window (3 built here)")
check(all(f["valid"][:16] >= "2021-08-28T05:37" for f in fr), "frames start at the LCC evaluation start (05:37Z)")
check(all(os.path.exists(os.path.join(site, p)) for f in fr for p in f["images"].values()), "map layers rendered for every frame")
check(all(os.path.exists(os.path.join(site, f["data"])) and f.get("volume") and os.path.exists(os.path.join(site, f["volume"])) for f in fr),
      "data planes and the 3-D cross-section volume written")
check(all(f.get("kmlb", {}).get("mode") in ("full", "partial") for f in fr), f"KMLB hybrid used: {[f['kmlb']['mode'] for f in fr]}")
check(all(f["glm_flashes_30min"] >= 1 for f in fr), "GLM lightning on the maps")
mills = fr[0]["field_mills"]
check(len(mills) > 10 and any(r[6] for r in mills), f"field-mill markers from the real archive: {len(mills)} mills, e.g. {mills[0][:5]}")
check(m["levels_km"][:3] == [0.5, 0.75, 1.0] and len(m["levels_km"]) == 33, "33 archive levels for the cross-section")
check(os.path.exists(os.path.join(site, "index.html")) and "M.replay" in open(os.path.join(site, "index.html")).read(), "replay viewer copied")
open("/tmp/replay_site.txt", "w").write(site)
print(f"\n{len(FAILS)} failure(s)"); sys.exit(1 if FAILS else 0)

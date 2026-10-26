#!/usr/bin/env python3
"""
CloudScope case replays - score every 2-minute frame of the logged countdown windows with the same
pinned classifier as the climatologies, twice per frame: MRMS alone, and the KMLB + MRMS hybrid
(single-source columns). One set of downloads feeds both.

Inputs (all in this repo):
    countdown_pads.csv              window start/end (Z), vehicle, payload, pad - no LWO calls
    fieldmill/fieldmill_minutes.npz KSC 1-minute field-mill values inside the windows (-999 = missing)
and the archives the climatologies use (MRMS noaa-mrms-pds, KMLB unidata, GOES, the Cape GLM archive),
through climo_run.py.

Per window -> out/<case id>.json:
    frames      UTC times, every 2 min from 60 min before the window start to its end
    mrms, kmlb  per frame, per pad (mc.SITES order): status (0/1/2), red and yellow rule bits
                (mc.RULE_KEYS order), cloud class at the pad, 9 feature bytes (as the climatology)
    fm5, fm7    per frame, per pad: peak |E| (V/m) of any mill within 5 / 7 nmi over the previous
                15 minutes (-1 = no mill reported) - the 4.1.2 rule is applied in the page, so its
                threshold can be varied
    kmlb_info   per frame: KMLB volume used, its top tilt, how high it reached over LC-39A
    glm         per frame: whether the GLM window was complete

    python cases_run.py 2024-07 --procs 4 --out out          # every window starting that month
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import logging
import multiprocessing as mp
import os
import time

import numpy as np

import climo_run as CR
import kmlb_classify as K
import mrms_classify as mc

STEP_MIN, PRE_MIN = 2, 60
FM_LOOK_MIN, FM_NM, FM_WATCH_NM = 15, 5.0, 7.0
SAT_CACHE_MIN, WIND_CACHE_MIN = 10, 60
PAD_ALIAS = {"LC-36": "SLC-36", "LC-16": "SLC-20"}      # LC-16 (Terran 1) sits 0.7 nmi from SLC-20
FM_SITES = {1: (28.70363, -80.66857), 2: (28.68755, -80.71951), 4: (28.66433, -80.63913),
            5: (28.65818, -80.69936), 6: (28.64397, -80.66639), 7: (28.64238, -80.74762),
            8: (28.63888, -80.62254), 9: (28.62142, -80.60797), 10: (28.62412, -80.70151),
            11: (28.60576, -80.67387), 12: (28.60226, -80.64094), 13: (28.60205, -80.58942),
            14: (28.57852, -80.60859), 15: (28.57676, -80.64310), 16: (28.57530, -80.57311),
            17: (28.56205, -80.67003), 18: (28.55518, -80.70212), 19: (28.54948, -80.62039),
            20: (28.54170, -80.64443), 21: (28.52575, -80.62210), 22: (28.50693, -80.69359),
            24: (28.47859, -80.67487), 25: (28.42474, -80.66380), 26: (28.54938, -80.56699),
            27: (28.50308, -80.55812), 28: (28.46024, -80.52722), 29: (28.46256, -80.58356),
            30: (28.47511, -80.55842), 31: (28.42033, -80.59116), 32: (28.43688, -80.58010),
            33: (28.41532, -80.60582), 34: (28.44982, -80.56350), 35: (28.60205, -80.58942)}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(processName)s %(message)s")


def case_id(start, pad):
    pad = pad if isinstance(pad, str) and pad else "TEST"
    return f"{start:%Y%m%d_%H%M}_{pad.replace('-', '')}"


def load_windows(path="countdown_pads.csv"):
    import pandas as pd
    W = pd.read_csv(path, parse_dates=["start", "end"])
    W = W[W.match.isin(["good", "test"])].copy()
    # identical repeated log rows (Starlink 8-19, 18 Oct 2024, is in the workbook twice): keep one
    W = W.drop_duplicates(subset=["start", "end", "payload", "pad"], keep="first")
    W["pad"] = W["pad"].astype(object).where(W["pad"].notna(), None)     # test countdowns: no pad
    W["id"] = [case_id(s, p) for s, p in zip(W.start, W["pad"])]
    return W


class FieldMills:
    """Peak |E| near each pad over the previous 15 minutes, from the minute archive."""

    def __init__(self, path="fieldmill/fieldmill_minutes.npz"):
        z = np.load(path)
        ok = z["value"] != -999
        o = np.argsort(z["t"][ok], kind="stable")
        self.t, self.m, self.v = z["t"][ok][o], z["mill"][ok][o], np.abs(z["value"][ok][o].astype(np.int32))
        k = np.cos(np.radians(28.5))
        dist = lambda a, b: np.hypot((a[0] - b[0]) * 60, (a[1] - b[1]) * 60 * k)
        self.near = {r: {p: np.array([m for m, xy in FM_SITES.items() if dist(mc.SITES[p], xy) <= r])
                         for p in mc.SITES} for r in (FM_NM, FM_WATCH_NM)}

    def peaks(self, t):
        """{radius: [peak |E| per pad (mc.SITES order), -1 = no reading]} for the 15 min up to t."""
        tm = int(np.datetime64(t, "m").astype(np.int64))
        a, b = np.searchsorted(self.t, tm - FM_LOOK_MIN, side="right"), np.searchsorted(self.t, tm, side="right")
        m, v = self.m[a:b], self.v[a:b]
        out = {}
        for r, near in self.near.items():
            row = []
            for p in mc.SITES:
                sel = np.isin(m, near[p])
                row.append(int(v[sel].max()) if sel.any() else -1)
            out[r] = row
        return out


def pad_values(status, red, yel, cls, diag, la, lo, ltg_nm, pads):
    """The climatology's per-pad record: status, red/yellow bits, class, 9 feature bytes."""
    from scipy.ndimage import distance_transform_edt as _edt
    dlat_km, dlon_km = mc._spacing(la, lo)
    ji = [(int(np.argmin(np.abs(la - mc.SITES[p][0]))), int(np.argmin(np.abs(lo - mc.SITES[p][1])))) for p in pads]
    fv = np.full((len(pads), len(CR.FEAT_NAMES)), 255, np.uint8)
    for q, key in enumerate(CR.FEAT_DIST):
        msk = diag["feat"][key]
        dist = _edt(~msk, sampling=(dlat_km, dlon_km)) / 1.852 if msk.any() else None
        if key == "ltg" and ltg_nm is not None:
            dist = ltg_nm if dist is None else np.minimum(dist, ltg_nm)
        if dist is not None:
            for p_, (j, i) in enumerate(ji):
                fv[p_, q] = 255 if dist[j, i] > 25.4 else int(np.ceil(dist[j, i] * 10 - 1e-6))
    mr = diag["feat"]["mrr1"]
    for p_, (j, i) in enumerate(ji):
        fv[p_, -1] = int(np.clip(np.round(max(float(mr[j, i]), 0.0) * 2), 0, 254))
    st = [int(status[j, i]) for j, i in ji]
    rb = [sum(1 << b for b, k in enumerate(mc.RULE_KEYS) if red[k][j, i]) for j, i in ji]
    yb = [sum(1 << b for b, k in enumerate(mc.RULE_KEYS) if yel[k][j, i] and not red[k][j, i]) for j, i in ji]
    cl = [int(cls[j, i]) for j, i in ji]
    return {"status": st, "red": rb, "yel": yb, "cls": cl, "feat": fv.tolist()}


def drift_history(prev_att, prev_t, t, wind, la, lo):
    """Last frame's attached anvil, moved downwind - the climatology's detached-anvil history."""
    if prev_att is None or (t - prev_t) > datetime.timedelta(hours=1, minutes=5):
        return None
    from scipy.ndimage import shift as _shift
    dlat_km, dlon_km = mc._spacing(la, lo)
    hrs = (t - prev_t).total_seconds() / 3600.0
    if wind is not None:
        moved = _shift(prev_att.astype(np.float32), (-wind["v_kmh"] * hrs / dlat_km, wind["u_kmh"] * hrs / dlon_km),
                       order=0, cval=0.0) > 0.5
        r_nm = wind["unc_kmh"] * hrs / 1.852
    else:
        moved, r_nm = prev_att, mc.DRIFT_KMH * hrs / 1.852
    return mc.maximum_filter(moved.astype(np.uint8), footprint=mc._disc(max(r_nm, 0.5), dlat_km, dlon_km)) > 0


def score_window(w, fms):
    """Every frame of one window, MRMS and hybrid. Returns the case dict."""
    sess = CR._session()
    pads = list(mc.SITES)
    t0 = (w["start"] - datetime.timedelta(minutes=PRE_MIN)).to_pydatetime().replace(second=0, microsecond=0)
    t0 -= datetime.timedelta(minutes=t0.minute % STEP_MIN)
    t1 = w["end"].to_pydatetime()
    frames = []
    t = t0
    while t <= t1:
        frames.append(t)
        t += datetime.timedelta(minutes=STEP_MIN)
    case = {"id": w["id"], "start": w["start"].isoformat(), "end": w["end"].isoformat(), "vehicle": w["vehicle"],
            "payload": w["payload"], "pad": w["pad"], "pad_scored": PAD_ALIAS.get(w["pad"], w["pad"]),
            "launched": bool(w.get("launched_this_count", False)), "pads": pads, "rule_keys": mc.RULE_KEYS,
            "feat_names": CR.FEAT_NAMES, "frames": [], "mrms": [], "kmlb": [], "fm5": [], "fm7": [],
            "kmlb_info": [], "glm": [], "skipped": []}
    prev = {"mrms": (None, None), "kmlb": (None, None)}
    z0, z0_t, kcache, satc, windc = None, None, {}, {}, {}
    pool = cf.ThreadPoolExecutor(max_workers=4)
    for t in frames:
        try:
            urls = {k: CR.nearest(sess, p, t, CR.MATCH_MIN) for k, p in CR.ARCHIVE.items()}
            gone = [k for k in mc.ESSENTIAL if urls.get(k) is None] + (["cg"] if urls.get("cg") is None else [])
            if gone:
                case["skipped"].append([t.isoformat(), f"missing {gone}"])
                continue
            futs = {k: pool.submit(CR.fetch, sess, u, mc.PRODUCTS[k][1]) for k, u in urls.items() if u}
            su = CR.nearest(sess, CR.STEINER_DIR, t, CR.MATCH_MIN)
            sfut = pool.submit(CR.fetch, sess, su, -999.0) if su else None
            hit = CR.kmlb_nearest(sess, t)
            if hit and hit[1] not in kcache:
                kcache.clear()                                  # one volume serves 2-3 frames
                kcache[hit[1]] = pool.submit(CR.kmlb_load, sess, t)
            F, la, lo = {}, None, None
            for k, f in futs.items():
                F[k], fla, flo, _ = f.result()
                if la is None:
                    la, lo = fla, flo
            for k in mc.PRODUCTS:
                if k not in F:
                    F[k] = np.full((la.size, lo.size), mc.PRODUCTS[k][1], np.float32)
            if z0 is None or (t - z0_t).total_seconds() >= CR.FREEZING_EVERY_H * 3600:
                zu = CR.nearest(sess, CR.FREEZING_DIR, t, 45)
                if zu:
                    z0, z0_t = CR.fetch(sess, zu, None)[0], t
            zz = z0 if z0 is not None else np.full((la.size, lo.size), 4800.0, np.float32)
            lvl = sfut.result()[0] if sfut is not None else None
            sk, wk = t.replace(minute=t.minute - t.minute % SAT_CACHE_MIN), t.replace(minute=0)
            if sk not in satc:
                try:
                    satc.clear(); satc[sk] = CR.sat_tops_bt(sess, t, la, lo, float(np.nanmean(zz)))
                except Exception:
                    satc[sk] = None
            if wk not in windc:
                windc.clear(); windc[wk] = CR.anvil_wind(sess, t)
            sat, wind = satc[sk], windc[wk]
            flashes, _, glm_ok = CR.glm_flashes(sess, t)
            ltg_nm = mc.glm_distance(flashes, t.isoformat(), la, lo)[0] if glm_ok else None
            kvol = kcache[hit[1]].result()[0] if hit else None
            kf = None
            if kvol is not None:
                try:
                    kf = K.KmlbFrame(kvol, la, lo, None, zz, t.isoformat())
                except Exception as e:
                    logging.warning(f"{t:%Y-%m-%d %H:%MZ} KMLB: {type(e).__name__}: {e}")
            rec = {}
            for mode in ("mrms", "kmlb"):
                Fm = {k: v.copy() for k, v in F.items()}
                L = lvl
                if mode == "kmlb" and kf is not None:
                    kf.apply_fields(Fm)
                    L = kf.merge_level(lvl, CR.STEINER_KM) if lvl is not None else None
                sep = mc.separation_lite(L, CR.STEINER_KM, la, lo) if L is not None else None
                hist = drift_history(*prev[mode], t, wind, la, lo)
                status, red, yel, cls, top, diag = mc.evaluate(Fm, zz, la, lo, hist, None, sep, ltg_nm, sat)
                prev[mode] = ((cls == 6), t)
                rec[mode] = pad_values(status, red, yel, cls, diag, la, lo, ltg_nm, pads)
            fm = fms.peaks(t)
            case["frames"].append(t.isoformat())
            case["mrms"].append(rec["mrms"]); case["kmlb"].append(rec["kmlb"])
            case["fm5"].append(fm[FM_NM]); case["fm7"].append(fm[FM_WATCH_NM])
            ki = kf.info if kf is not None else {}
            case["kmlb_info"].append([ki.get("volume"), ki.get("top_deg"), ki.get("lc39a_top_km"), ki.get("mode", "none")])
            case["glm"].append(bool(glm_ok))
        except Exception as e:
            case["skipped"].append([t.isoformat(), f"{type(e).__name__}: {str(e)[:120]}"])
            logging.warning(f"{w['id']} {t:%H:%MZ}: {type(e).__name__}: {e}")
    pool.shutdown()
    return case


def do_windows(rows, out):
    fms = FieldMills()
    for w in rows:
        a = time.monotonic()
        case = score_window(w, fms)
        with open(os.path.join(out, f"{w['id']}.json"), "w") as f:
            json.dump(case, f, separators=(",", ":"))
        logging.info(f"{w['id']} {w['payload']}: {len(case['frames'])} frames, {len(case['skipped'])} skipped, "
                     f"{time.monotonic() - a:.0f} s")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("month", help="YYYY-MM: every window starting that month")
    ap.add_argument("--procs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--out", default="out")
    ap.add_argument("--only", default=None, help="comma-separated case ids (testing / re-runs)")
    a = ap.parse_args()
    W = load_windows()
    W = W[W.start.dt.strftime("%Y-%m") == a.month]
    if a.only:
        W = W[W["id"].isin(a.only.split(","))]
    os.makedirs(a.out, exist_ok=True)
    rows = [r for _, r in W.iterrows()]
    logging.info(f"{a.month}: {len(rows)} windows")
    if not rows:
        return
    k = max(1, min(a.procs, len(rows)))
    chunks = [rows[i::k] for i in range(k)]
    if k == 1:
        do_windows(chunks[0], a.out)
    else:
        with mp.get_context("spawn").Pool(k) as pool:
            pool.starmap(do_windows, [(c, a.out) for c in chunks])


if __name__ == "__main__":
    main()

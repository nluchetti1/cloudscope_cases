#!/usr/bin/env python3
"""
Radar replay for one case: the LIVE KMLB viewer's frames - maps, cross-section volume, lightning,
field-mill markers, pad readouts - rebuilt from the archives for every KMLB volume whose scan
midpoint falls in the case's LCC evaluation window. One frame per volume, so each matches a GR2
volume one-for-one.

The live code renders it: replay_engine/ holds copies of the live KMLB page's mrms_classify.py
(v23, hooked) and kmlb_classify.py, and build_frame() is called exactly as the live job calls it.
Only the inputs change - archive files for the frame's time instead of the newest feeds:
    MRMS 2-D products, freezing level, 3-D levels   noaa-mrms-pds (via climo_run.nearest)
    KMLB Level II                                   the live Hybrid, which lists any day's volumes
    GLM                                             the Cape GLM archive (climo_run.glm_flashes)
    GOES cloud tops, anvil winds                    climo_run.sat_tops_bt / anvil_wind (GOES-16/19)
    field mills                                     fieldmill/fieldmill_minutes.npz
    isotherms                                       freezing level + lapse rate (as the case lanes;
                                                    no historical BUFKIT)
MERLIN has no archive before mid-2026, so replays of earlier cases have none.

    python replay_run.py 20220701_1900_SLC41 --out out      -> out/replay/<id>/ (viewer + frames)
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import logging
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "replay_engine")
LEVELS_KM = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
             6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
_NOW = {"t": None, "z0": None}                 # the frame being built, for the archive patches


def setup(out_site):
    """Import the live engine with OUT_DIR pointing at the replay folder, and patch its inputs."""
    os.environ["OUT_DIR"] = out_site
    sys.path.insert(0, ENGINE)
    sys.path.insert(1, HERE)
    import mrms_classify as M                  # the live v23 copy in replay_engine/
    import kmlb_classify as K
    import climo_run as CR                     # archive helpers; its mrms_classify is the same module
    assert os.path.dirname(os.path.abspath(M.__file__)) == ENGINE, "live engine not first on the path"
    M.HYBRID = K.Hybrid()
    M.VIEWER_VERSION_EXPECTED = K.KMLB_VERSION

    def fetch_volume(sess, levels, shape):
        """The 3-D volume from the archive, at the frame's time (the live one reads .latest)."""
        t = _NOW["t"]

        def one(item):
            name, h = item
            url = CR.nearest(sess, name, t, CR.MATCH_MIN)
            if not url:
                return h, None, None
            try:
                sub, _, _, v = M.decode_crop(M.fetch_url(sess, url), -999.0)
                return h, (sub if sub.shape == shape else None), v
            except Exception as e:
                logging.warning(f"3-D {h:g} km: {type(e).__name__}: {e}")
                return h, None, None
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            got = list(pool.map(one, levels))
        import numpy as np
        ok = [(h, s, v) for h, s, v in got if s is not None]
        if len(ok) < M.VOL_MIN_LEVELS:
            return None, None, None, f"only {len(ok)} of {len(levels)} archive levels readable"
        failed = [f"{h:g}" for h, s, _ in got if s is None]
        valids = {v for _, _, v in ok if v}
        return (np.stack([s for _, s, _ in ok]), np.array([h for h, _, _ in ok]),
                (max(valids) if valids else None),
                f"{len(ok)} archive levels" + (f", missing {failed}" if failed else ""))

    def goes_tops(sess, valid_iso, la, lo, cache):
        import numpy as np
        z = _NOW["z0"]
        sat = CR.sat_tops_bt(sess, _NOW["t"], la, lo, float(np.nanmean(z)) if z is not None else 4800.0)
        return sat, ("GOES ABI archive" if sat is not None else "GOES archive: no usable scan")
    M.fetch_volume, M.goes_tops = fetch_volume, goes_tops
    return M, K, CR


def volume_times(K, sess, start, end):
    """Midpoints of the KMLB volumes inside [start, end] - one replay frame each."""
    days = sorted({(start - dt.timedelta(minutes=15)).date(), start.date(), end.date()})
    vols = sorted(v for d in days for v in K.list_day(sess, d))
    mids = []
    for t, key in vols:
        m = t + dt.timedelta(minutes=K.MID_EST_MIN)
        if start <= m <= end:
            mids.append((m.replace(microsecond=0), key))
    return mids


def local_feeds(fms_path, FM_SITES, start, end):
    """The live builder's local-sensor input, from the field-mill minute archive."""
    import numpy as np
    z = np.load(fms_path)
    t0 = int(np.datetime64(start - dt.timedelta(minutes=30), "m").astype(np.int64))
    t1 = int(np.datetime64(end, "m").astype(np.int64))
    sel = (z["t"] >= t0) & (z["t"] <= t1) & (z["value"] != -999)
    rows = []
    for tm, m, v in zip(z["t"][sel], z["mill"][sel], z["value"][sel]):
        pos = FM_SITES.get(int(m))
        if pos:
            rows.append((int(m), pos[0], pos[1], dt.datetime(1970, 1, 1) + dt.timedelta(minutes=int(tm)), float(v)))
    newest = max((r[3] for r in rows), default=None)
    empty = {"pts": [], "from": None, "to": None, "ok": False, "note": "MERLIN: no archive before mid-2026"}
    return {"now": end, "cg": dict(empty), "cc": dict(empty),
            "fm": {"rows": rows, "from": start - dt.timedelta(minutes=30), "to": end, "mode": "range", "ok": True,
                   "note": f"Field mills: KSC 1-minute archive ({len(rows)} readings)", "newest": newest}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--out", default="out")
    ap.add_argument("--max-frames", type=int, default=60)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    site = os.path.join(os.path.abspath(a.out), "replay", a.case)
    os.makedirs(os.path.join(site, "frames"), exist_ok=True)
    M, K, CR = setup(site)
    import cases_run as C                      # window table, mill positions
    import numpy as np
    W = C.load_windows()
    row = W[W["id"] == a.case]
    if row.empty:
        sys.exit(f"no case {a.case!r} in countdown_pads.csv")
    w = row.iloc[0]
    start, end = w["start"].to_pydatetime(), w["end"].to_pydatetime()
    sess = CR._session()
    allv = volume_times(K, sess, start, end)
    mids = allv[:a.max_frames]
    logging.info(f"{a.case} {w['payload']}: window {start:%H:%M}-{end:%H:%M}Z, {len(mids)} KMLB volumes")
    if not mids:
        sys.exit("no KMLB volumes in the window")
    local = local_feeds(os.path.join(HERE, "fieldmill", "fieldmill_minutes.npz"), C.FM_SITES, start, end)
    levels = [(f"MergedReflectivityQC_{h:05.2f}", h) for h in LEVELS_KM]
    frames, la = [], None
    z0, z0_t = None, None
    for t, key in mids:
        t0 = time.monotonic()
        _NOW["t"] = t
        src = {k: (CR.nearest(sess, CR.ARCHIVE[k], t, CR.MATCH_MIN) if k in CR.ARCHIVE else None) for k in M.PRODUCTS}
        if z0 is None or (t - z0_t).total_seconds() >= 3600:
            zu = CR.nearest(sess, CR.FREEZING_DIR, t, 45)
            if zu:
                z0, z0_t = CR.fetch(sess, zu, None)[0], t
        _NOW["z0"] = z0
        flashes, _, glm_ok = CR.glm_flashes(sess, t)
        goes = {"cache": {}, "wind": CR.anvil_wind(sess, t)}
        frame, fla, flo = M.build_frame(sess, src, z0, levels=levels, prior=frames, snd=None, steiner_src=None,
                                        glm={"ok": glm_ok, "flashes": flashes}, goes=goes, local=local)
        if frame is None:
            logging.warning(f"{t:%H:%M:%SZ} ({os.path.basename(key)}): frame withheld")
            continue
        frame["kmlb_volume_key"] = key
        frames.append(frame)
        if la is None:
            la, lo = fla, flo
        logging.info(f"{t:%H:%M:%SZ} {os.path.basename(key)}: frame in {time.monotonic() - t0:.0f} s")
    if not frames:
        sys.exit("no frame could be built")
    try:
        gifs = M.build_gifs(sorted(frames, key=lambda f: f["valid"], reverse=True))
    except Exception as e:
        logging.warning(f"GIF export failed: {type(e).__name__}: {e}")
        gifs = {}
    newest = max(frames, key=lambda f: f["valid"])
    manifest = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gifs": gifs, "viewer_expected": M.VIEWER_VERSION_EXPECTED,
        "valid": newest["valid"], "freezing": {"source": "MRMS Model_0degC_Height (archive)"}, "domain": M.DOMAIN,
        "grid": {"ny": int(la.size), "nx": int(lo.size), "lat_n": float(la[0]), "lon_w": float(lo[0]),
                 "dlat": abs(float(la[0] - la[1])), "dlon": abs(float(lo[1] - lo[0]))},
        "sites": {k: list(v) for k, v in M.SITES.items()},
        "frames": frames,
        "rule_keys": M.RULE_KEYS, "rules": M.RULE_NAMES, "rule_how": M.RULE_HOW, "watch_how": M.WATCH_HOW,
        "not_evaluated": M.NOT_EVALUATED, "rules_off": M.RULES_OFF, "classes": M.CLASSES,
        "class_note": M.CLASS_NOTE, "top_levels": M.TOP_LEVELS, "levels_km": M._VOL_LEVELS or LEVELS_KM,
        "status": {str(k): {"name": v[0], "color": v[1]} for k, v in M.STATUS.items()},
        "refl": {"levels": M.REFL_LEVELS, "colors": M.REFL_COLORS},
        "thresholds": M.LLCC, "standard": "NASA-STD-4010 (2017-06-27)",
        "local_notes": [local[k]["note"] for k in ("cg", "cc", "fm")],
        "field_mill_colors": [[None if not np.isfinite(lim) else lim, c] for lim, c in M.FM_COLORS],
        "replay": {"id": a.case, "payload": w["payload"], "vehicle": w["vehicle"], "pad": w["pad"],
                   "start": start.isoformat() + "Z", "end": end.isoformat() + "Z",
                   "launched": bool(w.get("launched_this_count", False)), "volumes": len(allv),
                   "frames": len(frames)},
    }
    with open(os.path.join(site, "manifest.json"), "w") as fp:
        json.dump(manifest, fp, indent=1)
    shutil.copy(os.path.join(ENGINE, "viewer.html"), os.path.join(site, "index.html"))
    logging.info(f"replay {a.case}: {len(frames)} of {len(mids)} volume frames -> {site}")


if __name__ == "__main__":
    main()

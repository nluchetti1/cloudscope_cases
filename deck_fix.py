"""Stratiform-deck fixes (kv01 / Vulcan, 13 Nov 2026), applied to a classifier copy.
    python deck_fix.py <mrms_classify.py>

What the kv01 replay showed (post-frontal elevated deck, no convection, no lightning):
 1. False cumulus: 90-100% of cumulus cells were Steiner-"convective" only by the isolated-cell
    rule. The deck's fall streaks reach the ~3 km Steiner level as a few small patches, each
    "isolated" at that level, though every one sat inside a composite echo mass of 10^4 km2.
    Fix: a small object keeps isolated-cell status only where it is not embedded in a large
    composite echo mass, or where its echo reaches down to ROOT_KM (or the radar is blind below).
 2. Satellite-raised cumulus: echo based at ~4.5 km, nothing at the Steiner level, but no
    isotherm-product echo either, so the elevated test missed it and satellite raised it to
    "colder than -20 C". Fix: a 3-D echo base above the Steiner level also makes echo elevated.
 3. Attached anvil over the whole deck (10:14, 12:06): the "cores" were 24-25 dBZ cells based at
    3 km, cores only because VII > 0. Fix: VII makes a core only in a column rooted within
    ROOT_KM of the ground (or blind below); 40 dBZ composite still makes one anywhere.
 4. Detached anvil over the whole deck at the first frame: no history, so every floating echo
    defaulted to detached. Fix: with no history, floating echo is detached only if the frame has a
    convective core somewhere; otherwise it is an elevated layer.
Single-level frames (separation_lite: no echo bases) keep the old behaviour for 1-3.
"""
import sys

FIX_TAG = "DECK_FIX_KV01"


def patch(path):
    s = open(path).read()
    if FIX_TAG in s:
        print(f"{path}: already patched"); return
    def rep(old, new):
        nonlocal s
        assert s.count(old) == 1, (path, s.count(old), old[:70])
        s = s.replace(old, new)

    # --- settings
    rep('ISOLATED_KM2 = float(np.pi * 11.0 ** 2)      # ~380 km2, the background window\'s area\n',
        'ISOLATED_KM2 = float(np.pi * 11.0 ** 2)      # ~380 km2, the background window\'s area\n'
        f'# {FIX_TAG} (see deck_fix.py). An echo column is ROOTED when its 3-D echo base is at or below\n'
        '# ROOT_KM, or the radar cannot see under it. Cumulus bases here are ~1 km; a deck\'s fall\n'
        '# streaks end ~2.5-3 km up. Rooted-or-blind is the conservative side of every test that uses it.\n'
        'ROOT_KM = 2.0\n')

    # --- 1. isolated-cell rule: not for patches embedded in a large echo mass and not rooted
    rep('def steiner_conv_strat(z, dlat_km, dlon_km):',
        'def steiner_conv_strat(z, dlat_km, dlon_km, comp=None, rooted=None):')
    rep('''        small = area <= ISOLATED_KM2
        small[0] = False
        conv |= small[lab]''',
        '''        small = area <= ISOLATED_KM2
        small[0] = False
        iso = small[lab]
        if comp is not None and rooted is not None:
            # A patch "isolated" at this level but inside a large composite echo mass is the
            # underside of that mass (a deck's fall streaks), not a lone cell - unless its echo
            # reaches the ground (rooted) or the radar cannot see. kv01: every false cumulus.
            labc, nc = label(comp >= 0.0, structure=np.ones((3, 3)))
            if nc:
                areac = np.bincount(labc.ravel(), minlength=nc + 1) * dlat_km * dlon_km
                big = (areac > ISOLATED_KM2)[labc] & (labc > 0)
                iso &= ~(big & ~rooted)
        conv |= iso''')

    # --- separation(): echo base, rootedness, composite from the volume
    rep('''    lvl = vol[k]
    dlat_km, dlon_km = _spacing(la, lo)
    conv, strat = steiner_conv_strat(lvl, dlat_km, dlon_km)
    known = lvl > -900.0
    base_idx = (vbase & 63).astype(int)
    has = vbase != 255
    base_h = np.where(has, np.asarray(heights)[np.clip(base_idx, 0, len(heights) - 1)] * 1000.0,
                      np.inf)
    blind_below = has & ((vbase & 64) > 0)''',
        '''    lvl = vol[k]
    dlat_km, dlon_km = _spacing(la, lo)
    base_idx = (vbase & 63).astype(int)
    has = vbase != 255
    base_h = np.where(has, np.asarray(heights)[np.clip(base_idx, 0, len(heights) - 1)] * 1000.0,
                      np.inf)
    blind_below = has & ((vbase & 64) > 0)
    rooted = has & (blind_below | (base_h <= ROOT_KM * 1000.0))
    comp3d = np.max(np.where(vol > -900.0, vol, -99.0), axis=0)
    conv, strat = steiner_conv_strat(lvl, dlat_km, dlon_km, comp3d, rooted)
    known = lvl > -900.0''')
    rep('''            "below0": has & ((base_h < z0_m) | blind_below), "level_km": float(heights[k])}''',
        '''            "below0": has & ((base_h < z0_m) | blind_below), "level_km": float(heights[k]),
            "rooted": rooted, "base_m": np.where(has & ~blind_below, base_h, np.nan)}''')

    # --- 3. VII makes a core only where the column is rooted
    rep('''    core = (comp >= L["core_dbz"]) | (F["vii"] > 0.0)''',
        '''    # VII > 0 alone made 24 dBZ cells in an elevated ice deck "cores" (kv01, 10:14 and 12:06), and the
    # whole deck became attached anvil. VII now counts only in a rooted column (sep["rooted"]:
    # echo within ROOT_KM of the ground, or blind below); without a volume, as before.
    vii_ok = sep["rooted"] if (sep is not None and sep.get("rooted") is not None) else True
    core = (comp >= L["core_dbz"]) | ((F["vii"] > 0.0) & vii_ok)''')

    # --- 2. a 3-D echo base above the Steiner level also makes echo elevated
    rep('''    elev = (echo & sep["clear_low"] & (any_iso | aloft)) if sep is not None \\''',
        '''    base_aloft = np.zeros(comp.shape, bool)
    if sep is not None and sep.get("base_m") is not None:
        with np.errstate(invalid="ignore"):
            base_aloft = sep["base_m"] > sep["level_km"] * 1000.0      # kv01 12:48: based at 4.5 km
    elev = (echo & sep["clear_low"] & (any_iso | aloft | base_aloft)) if sep is not None \\''')

    # --- 4. no history: detached only if there is convection in the frame
    rep('''    if history is None:
        detached = floating
        elevated = np.zeros(comp.shape, bool)''',
        '''    if history is None:
        # No history (first frame of a run or replay): detached only if the frame has a convective
        # core somewhere - an anvil needs a parent. kv01's first frame called a post-frontal deck
        # with no convection in sight detached anvil end to end.
        detached = floating if core.any() else np.zeros(comp.shape, bool)
        elevated = floating & ~detached''')
    open(path, "w").write(s)
    print(f"{path}: patched")


LITE_TAG = "DECK_FIX_KV01_LITE"


def patch_lite(path):
    """Stage 2: the same fixes on single-level frames (separation_lite), using the MRMS 2.0 km
    level as the ROOTED test - echo there, or no coverage (blind), means rooted. Probe 16 Nov 2026:
    MergedReflectivityQC_02.00 is in the archive 2020-2026, same format as 03.00; over the map 54
    no-coverage cells against 1,331 at 1.50 km. kv01 10:14: 1,341 echo cells at 3 km, 203 at 2 km."""
    s = open(path).read()
    if LITE_TAG in s:
        print(f"{path}: lite stage already patched"); return
    assert FIX_TAG in s, "run stage 1 first"
    def rep(old, new):
        nonlocal s
        assert s.count(old) == 1, (path, s.count(old), old[:70])
        s = s.replace(old, new)
    rep('''def separation_lite(lvl, height_km, la, lo):''',
        '''def separation_lite(lvl, height_km, la, lo, comp=None, root=None):''')
    rep('''    dlat_km, dlon_km = _spacing(la, lo)
    conv, strat = steiner_conv_strat(lvl, dlat_km, dlon_km)
    known = lvl > -900.0
    return {"conv": conv, "strat": strat & known, "known": known, "below0": None,
            "clear_low": known & (lvl < 0.0), "level_km": float(height_km)}''',
        f'''    # {LITE_TAG}: root = the ROOT_KM level (MRMS 2.0 km, KMLB-merged on hybrid frames). With
    # it and the composite, the isolated-cell, VII-core and elevated fixes work here too; without
    # it (None), behaviour is as before.
    dlat_km, dlon_km = _spacing(la, lo)
    rooted = base_m = None
    if root is not None and comp is not None:
        rooted = (root >= 0.0) | (root <= -900.0)                 # echo at 2 km, or radar blind there
        with np.errstate(invalid="ignore"):
            aloft_only = (comp >= 0.0) & (lvl > -900.0) & (lvl < 0.0) & (root > -900.0) & (root < 0.0)
        base_m = np.where(aloft_only, (float(height_km) + 0.5) * 1000.0, np.nan)   # base above this level
    conv, strat = steiner_conv_strat(lvl, dlat_km, dlon_km, comp if rooted is not None else None, rooted)
    known = lvl > -900.0
    return {{"conv": conv, "strat": strat & known, "known": known, "below0": None,
            "clear_low": known & (lvl < 0.0), "level_km": float(height_km),
            "rooted": rooted, "base_m": base_m}}''')
    open(path, "w").write(s)
    print(f"{path}: lite stage patched")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        patch(p)
        patch_lite(p)

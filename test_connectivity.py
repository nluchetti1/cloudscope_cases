"""LLCCR 35 connectivity (CONNECT_CUMULUS) on hand-built storms.   python test_connectivity.py"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mrms_classify as mc
FAILS = []
def check(c, m):
    print(("  ok    " if c else "  FAIL  ") + m)
    if not c: FAILS.append(m)
LA = np.round(29.595 - 0.01 * np.arange(200), 3); LO = np.round(-81.595 + 0.01 * np.arange(200), 3)
P = mc.SITES["LC-39A"]; jp, ip = int(np.argmin(np.abs(LA - P[0]))), int(np.argmin(np.abs(LO - P[1])))
LOg, LAg = np.meshgrid(LO, LA)
nm_e = (LOg - P[1]) * 60 * np.cos(np.radians(P[0]))          # nmi east of the pad
nm_n = (LAg - P[0]) * 60                                       # nmi north
def blank():
    F = {k: np.full((200, 200), fill, np.float32) for k, (_, fill, _) in mc.PRODUCTS.items()}
    F["cg"][:] = -1.0
    return F
def put(F, m, levels, comp=25.0, hmax=3000.0):
    for k in ("r0", "r5", "r10", "r15", "r20"):
        if k in levels: F[k][m] = 20.0
    F["comp"][m] = comp; F["hmax"][m] = hmax
z0 = np.full((200, 200), 4800.0, np.float32)
def run(F, sep=None, hist=None, on=False):
    mc.CONNECT_CUMULUS = on
    st, red, yel, cls, top, diag = mc.evaluate(F, z0, LA, LO, hist, None, sep, None, None)
    mc.CONNECT_CUMULUS = False
    return {k: bool(v[jp, ip]) for k, v in red.items()}, diag

core = (np.abs(nm_e - 12) <= 1.0) & (np.abs(nm_n) <= 1.0)           # reaches -20 C, 11-13 nmi east
bridge = (nm_e >= 8) & (nm_e < 11) & (np.abs(nm_n) <= 0.6)         # warm cumulus, 8-11 nmi east
print("1. cold core 12 nmi out, connected by warm cumulus reaching to 8 nmi")
F = blank(); put(F, core, {"r0", "r5", "r10", "r15", "r20"}); put(F, bridge, {"r0"})
off, _ = run(F); on, d = run(F, on=True)
check(not off["cumulus_10nm"], "off: no -20 C cumulus within 10 nmi (the core is at 11 nmi)")
check(on["cumulus_10nm"], "on: the connected cloud's nearest edge is 8 nmi away -> violating (LLCCR 35)")
check(on["cumulus_5nm"] is False, "on: still nothing within 5 nmi")
print("2. the same, but the bridge is stratiform (layered) echo")
known = core | bridge
sep = {"conv": core.copy(), "strat": bridge.copy(), "known": known, "below0": None,
       "clear_low": np.zeros((200, 200), bool), "level_km": 3.0}           # as separation_lite returns
off2, _ = run(F, sep=sep); on2, _ = run(F, sep=sep, on=True)
check(not off2["cumulus_10nm"] and not on2["cumulus_10nm"], "layered echo does not connect cumulus (4.3c): clear both ways")
print("3. isolated cold core at 12 nmi, no bridge")
F3 = blank(); put(F3, core, {"r0", "r5", "r10", "r15", "r20"})
check(not run(F3)[0]["cumulus_10nm"] and not run(F3, on=True)[0]["cumulus_10nm"], "nothing connected: clear both ways")
print("4. 4.3b: detached anvil touching cumulus colder than -10 C")
F4 = blank()
cu = (np.abs(nm_e - 6) <= 0.8) & (np.abs(nm_n - 6) <= 0.8)         # cumulus reaching -10 C, ~8.5 nmi NE
an = (np.abs(nm_e - 2.5) <= 2.7) & (np.abs(nm_n - 6) <= 0.8)       # aloft-only echo touching it, reaching to ~0.5 nmi E of the pad's meridian
put(F4, cu, {"r0", "r5", "r10"}, comp=25.0)
put(F4, an, {"r20"}, comp=10.0, hmax=8500.0); F4["super"][an] = 5.0
hist = np.ones((200, 200), bool)
_, d_off = run(F4, hist=hist); _, d_on = run(F4, hist=hist, on=True)
det_off, att_on, det_on = d_off["detached"][an].mean(), d_on["attached"][an].mean(), d_on["detached"][an].mean()
print(f"   anvil cells: off detached {det_off:.0%}; on attached {att_on:.0%}, detached {det_on:.0%}")
check(det_off > 0.9 and att_on > 0.9 and det_on < 0.1, "a detached anvil touching cumulus colder than -10 C is assessed as attached (4.3b)")
print("5. the default is off")
check(mc.CONNECT_CUMULUS is False, "CONNECT_CUMULUS defaults to False")
print(f"\n{len(FAILS)} failure(s)"); sys.exit(1 if FAILS else 0)

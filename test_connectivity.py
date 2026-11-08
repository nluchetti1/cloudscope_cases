"""LLCCR 35 connectivity on hand-built storms: CONNECT_CUMULUS (cumulus merging) and
CONNECT_ANVIL_43B (4.3b, 3-D contact).        python test_connectivity.py"""
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
nm_e = (LOg - P[1]) * 60 * np.cos(np.radians(P[0])); nm_n = (LAg - P[0]) * 60
def blank():
    F = {k: np.full((200, 200), fill, np.float32) for k, (_, fill, _) in mc.PRODUCTS.items()}
    F["cg"][:] = -1.0
    return F
def put(F, m, levels, comp=25.0, hmax=3000.0):
    for k in ("r0", "r5", "r10", "r15", "r20"):
        if k in levels: F[k][m] = 20.0
    F["comp"][m] = comp; F["hmax"][m] = hmax
z0 = np.full((200, 200), 4800.0, np.float32)
def run(F, sep=None, hist=None, cu=False, anvil=False):
    mc.CONNECT_CUMULUS, mc.CONNECT_ANVIL_43B = cu, anvil
    try:
        st, red, yel, cls, top, diag = mc.evaluate(F, z0, LA, LO, hist, None, sep, None, None)
    finally:
        mc.CONNECT_CUMULUS = mc.CONNECT_ANVIL_43B = False
    return {k: bool(v[jp, ip]) for k, v in red.items()}, diag

core = (np.abs(nm_e - 12) <= 1.0) & (np.abs(nm_n) <= 1.0)
bridge = (nm_e >= 8) & (nm_e < 11) & (np.abs(nm_n) <= 0.6)
print("1. cold core 12 nmi out, connected by warm cumulus reaching to 8 nmi")
F = blank(); put(F, core, {"r0", "r5", "r10", "r15", "r20"}); put(F, bridge, {"r0"})
check(not run(F)[0]["cumulus_10nm"], "off: no -20 C cumulus within 10 nmi (the core is at 11 nmi)")
on = run(F, cu=True)[0]
check(on["cumulus_10nm"] and not on["cumulus_5nm"], "cumulus connectivity on: the connected edge at 8 nmi violates; nothing within 5")
print("2. the same, but the bridge is stratiform (layered) echo")
sep = {"conv": core.copy(), "strat": bridge.copy(), "known": core | bridge, "below0": None,
       "clear_low": np.zeros((200, 200), bool), "level_km": 3.0}
check(not run(F, sep=sep)[0]["cumulus_10nm"] and not run(F, sep=sep, cu=True)[0]["cumulus_10nm"], "layered echo does not connect cumulus (4.3c)")
print("3. isolated cold core at 12 nmi")
F3 = blank(); put(F3, core, {"r0", "r5", "r10", "r15", "r20"})
check(not run(F3, cu=True)[0]["cumulus_10nm"], "nothing connected: clear")
print("4. 4.3b - detached anvil beside cumulus colder than -10 C")
cu = (np.abs(nm_e - 6) <= 0.8) & (np.abs(nm_n - 6) <= 0.8)
an = (np.abs(nm_e - 2.5) <= 2.7) & (np.abs(nm_n - 6) <= 0.8)
hist = np.ones((200, 200), bool)
def anvil_case(cu_levels, an_levels):
    F4 = blank(); put(F4, cu, cu_levels, comp=25.0)
    put(F4, an, an_levels, comp=10.0, hmax=8500.0); F4["super"][an] = 5.0
    return F4
def share(d, key): return d[key][an].mean()
Fa = anvil_case({"r0", "r5", "r10"}, {"r20"})           # anvil base ~7.9 km, cumulus top ~6.3 km: 1.6 km apart
_, d0 = run(Fa, hist=hist)
check(share(d0, "detached") > 0.9, f"setup: the anvil is detached with both switches off ({share(d0, 'detached'):.0%})")
_, d1 = run(Fa, hist=hist, cu=True)
check(share(d1, "detached") > 0.9, "4a: cumulus connectivity alone leaves it detached (4.3b has its own switch)")
_, d2 = run(Fa, hist=hist, anvil=True)
check(share(d2, "detached") > 0.9 and share(d2, "attached") < 0.1,
      "4b: 4.3b on, but the anvil floats 1.6 km above the cumulus top - not touching, stays detached")
Fc = anvil_case({"r0", "r5", "r10", "r15"}, {"r15", "r20"})   # anvil base ~7.1 km, cumulus top ~7.1 km
_, d3 = run(Fc, hist=hist)
_, d4 = run(Fc, hist=hist, anvil=True)
print(f"   touching case: off detached {share(d3, 'detached'):.0%}; 4.3b on attached {share(d4, 'attached'):.0%}")
check(share(d3, "detached") > 0.9 and share(d4, "attached") > 0.9, "4c: anvil reaching down to the cumulus top - physically connected, assessed as attached")
print("5. defaults")
check(mc.CONNECT_CUMULUS is False and mc.CONNECT_ANVIL_43B is False and mc.ANVIL_CONTACT_M == 1000.0, "both switches off by default; contact tolerance 1 km")
print(f"\n{len(FAILS)} failure(s)"); sys.exit(1 if FAILS else 0)

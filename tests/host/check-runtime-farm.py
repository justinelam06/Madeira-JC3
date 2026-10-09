#!/usr/bin/env python3
"""The VC++ runtimes in the ARM64EC DLL farm (app/Madeira/arm64ec-windows); no Wine runs.

A 64-bit game that imports a runtime the farm lacks never runs an instruction: the loader stops
with c0000135 (Metro 2033 Redux on MSVCP110, Just Cause 3 on MSVCR100/MSVCP100).

Part A: every VC++ runtime a 64-bit game imports from system32 (2005 to 2015-2022) is in the farm,
and each is Wine's ARM64EC builtin: the "Wine builtin DLL" DOS stub, AMD64 machine and a CHPE
metadata pointer. A Microsoft x86_64 binary (not redistributable here, tools/fetch-vcruntime.md)
or a plain x64 build fails this.  Part B: msvcrNNN and msvcpNNN come in pairs.  Part C: every
import and delay import of every module in the farm resolves inside the farm (API sets resolve
through apisetschema), apart from the gaps listed in KNOWN_GAPS, which predate this check.
"""
from pathlib import Path
import struct

root = Path(__file__).resolve().parents[2]
farm = root / "app/Madeira/arm64ec-windows"

RUNTIMES = ["msvcrt", "ucrtbase",
            "msvcr80", "msvcr90", "msvcr100", "msvcr110", "msvcr120",
            "msvcp80", "msvcp90", "msvcp100", "msvcp110", "msvcp120",
            "msvcp140", "msvcp140_1", "msvcp140_2", "msvcp140_atomic_wait", "msvcp140_codecvt_ids",
            "vcruntime140", "vcruntime140_1", "concrt140"]
PAIRED = ["80", "90", "100", "110", "120"]
# (importer, kind, imported DLL): missing before this check was written. Shrink, do not grow.
KNOWN_GAPS = {("bthprops.cpl", "import", "bluetoothapis.dll"),
              ("mf.dll", "delay", "evr.dll"),
              ("opengl32.dll", "delay", "glu32.dll"),
              ("shell32.dll", "delay", "shdocvw.dll"),
              ("urlmon.dll", "delay", "advpack.dll")}


def parse(path):
    d = path.read_bytes()
    if d[:2] != b"MZ" or len(d) < 0x40:
        return None
    pe = struct.unpack_from("<I", d, 0x3c)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        return None
    machine, nsec = struct.unpack_from("<HH", d, pe + 4)
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    dirs = opt + (112 if struct.unpack_from("<H", d, opt)[0] == 0x20b else 96)
    secs, s = [], opt + optsz
    for _ in range(nsec):
        vsize, va, rsize, ptr = struct.unpack_from("<IIII", d, s + 8)
        secs.append((va, max(vsize, rsize), ptr))
        s += 40

    def off(rva):
        return next(rva - va + ptr for va, size, ptr in secs if va <= rva < va + size)

    def name(rva):
        o = off(rva)
        return d[o:d.index(b"\0", o)].decode("ascii").lower()

    def table(index, entry, name_at):
        rva = struct.unpack_from("<I", d, dirs + 8 * index)[0]
        names, o = [], off(rva) if rva else None
        while o is not None and struct.unpack_from("<I", d, o + name_at)[0]:
            names.append(name(struct.unpack_from("<I", d, o + name_at)[0]))
            o += entry
        return names

    chpe = 0
    lc_rva, lc_size = struct.unpack_from("<II", d, dirs + 8 * 10)
    if lc_rva and lc_size > 0xc8 and machine == 0x8664:
        chpe = struct.unpack_from("<Q", d, off(lc_rva) + 0xc8)[0]   # CHPEMetadataPointer
    return {"builtin": d[0x40:0x50] == b"Wine builtin DLL", "machine": machine, "chpe": chpe,
            "import": table(1, 20, 12), "delay": table(13, 32, 4)}


have = {p.name.lower(): p for p in farm.iterdir()}

for r in RUNTIMES:
    p = have.get(r + ".dll")
    assert p, f"{r}.dll is missing from the farm: a game importing it stops with c0000135"
    info = parse(p)
    assert info and info["builtin"], f"{r}.dll is not a Wine builtin"
    assert info["machine"] == 0x8664 and info["chpe"], f"{r}.dll is not an ARM64EC image"
print(f"PASS: {len(RUNTIMES)} VC++ runtimes, each a Wine ARM64EC builtin")

for v in PAIRED:
    assert (f"msvcr{v}.dll" in have) == (f"msvcp{v}.dll" in have), f"msvcr{v}/msvcp{v} not paired"
print(f"PASS: msvcr/msvcp paired for {', '.join(PAIRED)}")

found, modules = set(), 0
for p in sorted(have.values()):
    info = parse(p)
    if not info:
        continue
    modules += 1
    for kind in ("import", "delay"):
        for dll in info[kind]:
            if dll not in have and not dll.startswith(("api-ms-win-", "ext-ms-")):
                found.add((p.name.lower(), kind, dll))
new = found - KNOWN_GAPS
assert not new, "unresolved imports in the farm:\n  " + "\n  ".join("%s %s %s" % g for g in sorted(new))
fixed = KNOWN_GAPS - found
print(f"PASS: imports of {modules} modules resolve in the farm ({len(found)} known gaps"
      + (f"; no longer missing, drop from KNOWN_GAPS: {sorted(fixed)}" if fixed else "") + ")")

"""Print the search patterns for files/fixes.lua from the Steam noita.exe (Jan 25 2025).

Each pattern is the patched bytes plus at least CONTEXT bytes of whole instructions on each
side, grown until it matches once in the exe's code. Bytes that move between builds of the same
code are wildcards (??): rel32 branch/call fields, and in the context also 4-byte immediates and
displacements that point into the image. Inside a hooked region only rel32 fields are wildcards;
their targets become named symbols. A test checks fixes.lua against this output.
Usage: uv run tools/make_patterns.py [path/to/noita.exe]
"""
from pathlib import Path
import re
import struct
import sys

import capstone

STEAM_EXE = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Noita\noita.exe")
CONTEXT = 16
# fix id -> sites as (va, length, kind); kind "bytes" (replaced in place), "hook" or "call"
SITES = {
    "bounds": [(0x7246B5, 7, "bytes"), (0x7246BC, 7, "bytes"), (0xAD0EE2, 8, "bytes"),
               (0xAD0F08, 8, "bytes"), (0xAD1CE4, 8, "bytes"), (0xAD1D01, 8, "bytes")],
    "pixel_scene_dedup": [(0x87F8BA, 6, "bytes")],
    "explosion_angles": [(0x659846, 45, "hook")],
    "contact_walk": [(0x9BD3DC, 106, "hook")],
    "sprite_stains": [(0xC226D4, 5, "call")],
    "far_rays": [(0x95CB07, 5, "call"), (0x95CB0C, 9, "bytes"), (0x95CDA5, 5, "call"), (0x95CDAA, 9, "bytes")],
    "far_polygons": [(0x810865, 8, "bytes")],
}
# site va -> va the pattern must reach: patched short jumps whose target is past the context
COVER = {0x810865: 0x8108D5}
NAMES = {0x44A410: "sqrt", 0x44A330: "atan2", 0x9BD536: "found"}  # rel32 targets in hooked code

MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
MD.detail = True


class Exe:
    """An exe file's executable sections at their virtual addresses."""

    def __init__(self, data):
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        count, opt = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
        self.base, self.size = struct.unpack_from("<I", data, pe + 52)[0], struct.unpack_from("<I", data, pe + 80)[0]
        self.sections = []
        for n in range(count):
            at = pe + 24 + opt + 40 * n
            vsize, rva, rawsize, rawptr = struct.unpack_from("<IIII", data, at + 8)
            if struct.unpack_from("<I", data, at + 36)[0] & 0x20000000:
                raw = data[rawptr:rawptr + min(vsize, rawsize)]
                self.sections.append((self.base + rva, raw + bytes(vsize - len(raw))))

    def read(self, va, n):
        for start, raw in self.sections:
            if start <= va and va + n <= start + len(raw):
                return raw[va - start:va - start + n]
        raise ValueError(f"{va:#x} isn't in an executable section")

    def find(self, pattern):
        regex = re.compile(b"(?=" + b"".join(b"." if b is None else re.escape(bytes([b])) for b in pattern) + b")",
                           re.DOTALL)
        return [start + m.start() for start, raw in self.sections for m in regex.finditer(raw)]


def rel32_field(i):
    """Offset of a rel32 branch/call target field in instruction i, or None."""
    if i.size >= 5 and i.operands and i.operands[0].type == capstone.x86.X86_OP_IMM and (
            i.group(capstone.CS_GRP_JUMP) or i.group(capstone.CS_GRP_CALL)):
        return i.size - 4
    return None


def instructions(exe, lo, hi):
    """Instructions covering about [lo, hi), decoded from a start that lands on lo."""
    for back in range(64, 0, -1):
        out = list(MD.disasm(exe.read(lo - back, hi - lo + back + 64), lo - back))
        if any(i.address == lo for i in out):
            return out
    raise ValueError(f"no instruction boundary at {lo:#x}")


def pattern_for(exe, sites):
    """(start va, pattern with None = wildcard, symbols) for sites that share one pattern."""
    first, last = sites[0][0], max([sites[-1][0] + sites[-1][1]] + [COVER[s[0]] for s in sites if s[0] in COVER])
    ins = instructions(exe, first, last)
    lo = max(n for n, i in enumerate(ins) if i.address <= first - CONTEXT)
    hi = min(n for n, i in enumerate(ins) if i.address + i.size >= last + CONTEXT)
    while True:
        start, pattern, symbols = ins[lo].address, [], {}
        for i in ins[lo:hi + 1]:
            raw = list(i.bytes)
            site = next((s for s in sites if s[0] <= i.address < s[0] + s[1]), None)
            end = site and site[0] + site[1]
            while end and any(s[0] == end for s in sites):  # adjacent sites replace whole instructions together
                end += next(s[1] for s in sites if s[0] == end)
            if site and i.address + i.size > end:
                raise ValueError(f"site {site[0]:#x} ends inside an instruction")
            field = rel32_field(i)
            if field is not None and (site is None or site[2] != "bytes"):
                raw[field:] = [None] * 4
                if site:
                    target = i.address + i.size + struct.unpack_from("<i", i.bytes, field)[0]
                    symbols.setdefault(NAMES[target], []).append(i.address + field - start)
            if site is None:
                for off, size in ((i.disp_offset, i.disp_size), (i.imm_offset, i.imm_size)):
                    if off and size == 4 and exe.base <= struct.unpack_from("<I", i.bytes, off)[0] < exe.base + exe.size:
                        raw[off:off + 4] = [None] * 4
            pattern += raw
        if exe.find(pattern) == [start]:
            return start, pattern, symbols
        lo, hi = lo - 1, hi + 1


def groups(sites):
    """Sites whose context windows overlap, in order."""
    out = []
    for site in sites:
        if out and site[0] - CONTEXT <= out[-1][-1][0] + out[-1][-1][1] + CONTEXT:
            out[-1].append(site)
        else:
            out.append([site])
    return out


def patterns(exe):
    """fix id -> [(start va, pattern, [(site offset, length, kind)], symbols)]"""
    return {fix: [(start, pattern, [(va - start, n, kind) for va, n, kind in group], symbols)
                  for group in groups(sites) for start, pattern, symbols in [pattern_for(exe, group)]]
            for fix, sites in SITES.items()}


def hex_pattern(pattern):
    return "".join("??" if b is None else f"{b:02x}" for b in pattern)


def lua(found, steam_targets):
    """The patterns/symbols fields of one fix in files/fixes.lua (bytes sites still need patched)."""
    out = ["        patterns = {"]
    for start, pattern, sites, _ in found:
        text = hex_pattern(pattern)
        chunks = [text[n:n + 92] for n in range(0, len(text), 92)]
        lua_sites = ", ".join(
            f"{{at = {at}, patched = \"\"}}" if kind == "bytes" else
            f"{{at = {at}, hook = {n}}}" if kind == "hook" else f"{{at = {at}, call = true}}"
            for at, n, kind in sites)
        out.append(f"            {{va = 0x{start:X}, sites = {{{lua_sites}}},")
        out.append("             bytes = \"" + "\"\n                .. \"".join(chunks) + "\"},")
    out.append("        },")
    symbols = found[0][3]
    if symbols or any(kind == "hook" for _, _, kind in found[0][2]):
        fields = [f"{name} = {{rel32 = {{{', '.join(map(str, offsets))}}}, steam = 0x{steam_targets[name]:X}}}"
                  for name, offsets in symbols.items()]
        for at, n, kind in found[0][2]:
            if kind == "hook":
                fields.append(f"back = {{at = {at + n}, steam = 0x{found[0][0] + at + n:X}}}")
        out.append("        symbols = {" + ", ".join(fields) + "},")
    return "\n".join(out)


def main():
    exe = Exe((Path(sys.argv[1]) if len(sys.argv) > 1 else STEAM_EXE).read_bytes())
    steam_targets = {name: va for va, name in NAMES.items()}
    for fix, found in patterns(exe).items():
        print(f"    -- {fix}")
        print(lua(found, steam_targets))


if __name__ == "__main__":
    main()

"""Write PATCHES.txt: every change the mod makes, as disassembly.

Reads the patch table in files/fixes.lua (the same data the mod applies) and disassembles
every before/after with capstone, as in the build the fixes were made for. A test fails if the
checked-in PATCHES.txt is stale. Usage: uv run tools/describe_patches.py
"""
from pathlib import Path
import struct

import capstone
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "PATCHES.txt"
EXE_CAVE_VA, EXE_TABLE_VA = 0x12E9000, 0x12EA000
ABOUT = {
    "bounds": [
        "Bounding boxes start with max = 0x00800000 (FLT_MIN, the smallest positive float)",
        "instead of -FLT_MAX. Boxes of things west of / above the world centre (all",
        "coordinates < 0) then stretch to 0,0, and the 64-unit region searches over them",
        "get huge (lava, western sky, even while paused). Same-length immediates:",
        "RenderTiles draw jobs (0x7246b5, 0x7246bc) and two default boxes (0xad0ee2 ...).",
    ],
    "pixel scene dedup": [
        "LoadPixelScene's duplicate check (0x87f3d0) repeats its read-only scan of both",
        "pixel-scene lists once per pending scene. The outer loop's back-jump becomes a",
        "6-byte NOP: one pass, same result.",
    ],
    "explosion angles": [
        "Explosions call sqrt (0x44a410) and atan2 (0x44a330) for every cell of the blast",
        "square, but the angle depends only on the cell offset (dx, dy). The hook jumps",
        "to a cave that looks the angle up in a 1025 x 1025 table (offsets -512..512,",
        "zero = not filled yet, stored XOR 0x7fc00001). On a miss it runs the original",
        "instructions and stores the result; out-of-range offsets just run the original",
        "instructions. Both paths return to 0x659873.",
    ],
    "contact walk": [
        "Box2D's AddPair walks body B's whole contact list looking for an existing",
        "contact between the two fixtures. Every contact is in both bodies' lists, so",
        "the cave walks A's and B's lists side by side with the original match test and",
        "stops when either ends: same answer, ~2x the shorter list. Not found -> 0x9bd446",
        "(create the contact), found -> 0x9bd536 (return).",
    ],
    "sprite stains": [
        "SpriteStains calls atan2 on the entity's rotation for every pixel of the sprite.",
        "The call now goes to a one-entry memo: same inputs as last time -> return the",
        "stored angle, otherwise call the original atan2 and remember {y, x, angle} in a",
        "16-byte slot (one aligned read/write).",
    ],
    "far rays": [
        "Two ray functions (0x95c970, 0x95cc40; LoadPixelScene reaches the first) step one",
        "pixel at a time, x += dx, y += dy, until the distance walked reaches the ray's",
        "length. Past x ~16.7M floats are 2+ apart, so x + 1 == x: the ray never moves and",
        "the game hangs. The step now calls a cave doing the same two adds; only if",
        "neither x nor y changed, it moves the longer axis one float step (the float's",
        "bits +1 away from zero, -1 toward it) toward the target, so the ray keeps walking",
        "and checking cells, just coarser, and ends by the loop's own length test. A unit",
        "step always moves a coordinate below 2^24 (16.7M), so nothing changes there.",
        "Far-away fix: does nothing for players who don't go that far.",
    ],
    "far polygons": [
        "A worker job (0x810770) simplifies terrain outlines (0x927e10) and closes each",
        "result with push_back(front()). Far out the points collapse, the result is empty",
        "and front() is a null pointer: crash. The branch at 0x810865 only runs for an",
        "empty result; it now goes straight to the next outline (same bookkeeping as the",
        "loop, without adding the point), leaving the empty outline empty. Outputs start",
        "empty and the simplifier fills any outline of 3+ points, so this branch only runs",
        "where the original always crashed. Far-away fix: does nothing for players who",
        "don't go that far.",
    ],
}


def load_fixes():
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    return module, list(module.FIXES.values())


def symbol_fields(fix):
    """Pattern offset of each rel32 field that holds a symbol -> (name, target in the original build)."""
    out = {}
    for name, s in (fix.symbols.items() if fix.symbols else []):
        for at in (s.rel32.values() if s.rel32 else []):
            out[at] = (name.decode(), s.steam)
    return out


def original_bytes(fix, k):
    """Pattern k's bytes as in the original build: symbol fields filled, other ?? as 00."""
    p = fix.patterns[k]
    data = bytearray(bytes.fromhex(p.bytes.decode().replace("??", "00")))
    for at, (_, target) in (symbol_fields(fix).items() if k == 1 else []):  # symbols are in pattern 1
        struct.pack_into("<i", data, at, target - (p.va + at + 4))
    return bytes(data)


def site_length(site):
    return site.hook or (5 if site.call else len(site.patched) // 2)


def site_runs(p):
    """The pattern's sites in groups that touch end to end (together they replace whole instructions)."""
    runs = []
    for site in sorted(p.sites.values(), key=lambda s: s.at):
        if runs and runs[-1][-1].at + site_length(runs[-1][-1]) == site.at:
            runs[-1].append(site)
        else:
            runs.append([site])
    return runs


def disasm(md, code, va):
    out = list(md.disasm(code, va))
    if sum(i.size for i in out) != len(code):
        raise ValueError(f"Couldn't disassemble all bytes at {va:#x}")
    return out


def line(i, note=""):
    text = f"    {i.address:08x}  {i.bytes.hex(' '):<33} {i.mnemonic} {i.op_str}".rstrip()
    return f"{text:<88} ; {note}" if note else text


def float_note(i):
    if i.mnemonic == "mov" and i.operands and i.operands[-1].type == capstone.x86.X86_OP_IMM:
        value = struct.unpack("<f", struct.pack("<I", i.operands[-1].imm & 0xFFFFFFFF))[0]
        name = {0x00800000: "FLT_MIN", 0xFF7FFFFF: "-FLT_MAX"}.get(i.operands[-1].imm & 0xFFFFFFFF)
        return f"{value:.7g}" + (f" ({name})" if name else "")
    return ""


def cave_notes(fix, cave_va):
    """Offset of each adjusted field -> note."""
    code = bytes.fromhex(fix.code.decode())
    notes = {}
    for r in fix.rel.values():
        at, name = r[1], r[2].decode()
        target = cave_va + at + 4 + struct.unpack_from("<i", code, at)[0]
        notes[at] = f"adjusted at load: {name} ({target:#x} here)"
    for at in fix.abs.values():
        offset = struct.unpack_from("<I", code, at)[0] - EXE_TABLE_VA
        notes[at] = f"adjusted at load: data block +{offset:#x}"
    return notes


def pattern_lines(p):
    text = p.bytes.decode()
    return [f"    {text[n:n + 80]}" for n in range(0, len(text), 80)]


def describe():
    _, fixes = load_fixes()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    out = [
        "Lag Fixer: what changes in noita.exe's memory",
        "=" * 45,
        "Made for build 9dbd52ce (Jan 25 2025, PE timestamp 0x6794ee3c), image base 0x400000;",
        "addresses below are that build's. Generated by tools/describe_patches.py from",
        "files/fixes.lua (the table the mod applies); disassembly by capstone, Intel syntax.",
        "",
        "Each fix finds its code by searching noita.exe for the pattern(s) listed with it:",
        "the 'before' bytes plus surrounding code, ?? = any byte (address fields that move",
        "between builds of the same code). Nothing is written unless every pattern of the",
        "fix matches exactly once, in this build at exactly the address shown. On any other",
        "noita.exe nothing is written unless 'Other noita.exe versions' is on in Mod",
        "Settings. Fixes turned off in Mod Settings are left alone. noita.exe on disk and",
        "saves are never touched.",
        "",
        "Fixes 3-6 jump to added code in memory the mod allocates at startup: code 0x2d0 bytes",
        "(made execute/read-only after writing) and a zeroed 0x402020-byte data block (the",
        "angle table, then the stains slot at +0x402010). The added code is listed as if the",
        f"code were at {EXE_CAVE_VA:#x} and the data at {EXE_TABLE_VA:#x} (right after the exe image).",
        "Fields marked 'adjusted at load' are rewritten for the real allocation and for the",
        "addresses read from the matched code (follow the jump at a hooked address in a",
        "debugger to find it).",
    ]
    for n, fix in enumerate(fixes, 1):
        name = fix.name.decode()
        out += ["", "", f"{n}. {name}", "-" * (len(name) + 3), *ABOUT[name]]
        patterns = list(fix.patterns.values())
        for p in patterns:
            out += ["", f"  pattern at {p.va:#x}", *pattern_lines(p)]
        cave_va = EXE_CAVE_VA + fix.offset if fix.code else None
        for k, p in enumerate(patterns, 1):
            original = original_bytes(fix, k)
            for run in site_runs(p):
                start, length = run[0].at, sum(site_length(s) for s in run)
                before = disasm(md, original[start:start + length], p.va + start)
                fields = symbol_fields(fix) if k == 1 else {}
                out += ["", f"  before ({length} bytes)" if run[0].hook or len(run) > 1 else "  before"]
                for i in before:
                    at = i.address - p.va
                    name = next((v[0] for f, v in fields.items() if at <= f < at + i.size), "")
                    out.append(line(i, float_note(i) or name))
                out.append("  after")
                for site in run:
                    va, length = p.va + site.at, site_length(site)
                    if site.patched:
                        out += [line(i, float_note(i)) for i in disasm(md, bytes.fromhex(site.patched.decode()), va)]
                    else:
                        jump = (b"\xe9" if site.hook else b"\xe8") + struct.pack("<i", cave_va - (va + 5))
                        out.append(line(disasm(md, jump, va)[0], "adjusted at load: the cave"))
                        if site.hook:
                            out.append(f"    {va + 5:08x}  cc x {length - 5:<28} int3 (padding, never reached)")
        if fix.code:
            code = bytes.fromhex(fix.code.decode())
            notes = cave_notes(fix, cave_va)
            out += ["", f"  cave (code +{fix.offset:#x}, {len(code)} bytes)"]
            for i in disasm(md, code, cave_va):
                at = i.address - cave_va
                note = next((v for k, v in notes.items() if at <= k < at + i.size), "")
                out.append(line(i, note))
    return "\n".join(out) + "\n"


def main():
    OUTPUT.write_text(describe(), encoding="ascii", newline="\n")
    print(f"-> {OUTPUT}")


if __name__ == "__main__":
    main()

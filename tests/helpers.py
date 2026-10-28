"""A fake noita.exe image and process memory for running files/fixes.lua under Lupa."""
from pathlib import Path
import struct
import sys

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from describe_patches import original_bytes, site_length

IMAGE_BASE, TIMESTAMP = 0x400000, 0x6794EE3C
EXE_CAVE_VA, EXE_TABLE_VA = 0x12E9000, 0x12EA000
CODE_BYTES, DATA_BYTES = 0x2D0, 0x402020
IMAGE_BYTES = 0x900000  # covers every patched site
SECTION_TABLE = 0x80 + 24 + 0xE0


def fixes_module():
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    return lua.execute((ROOT / "files" / "fixes.lua").read_text())


def fix_list(module=None):
    return list((module or fixes_module()).FIXES.values())


def sites(fix, shift=0):
    """(va, site, pattern index) for every site of the fix, its code moved by shift."""
    return [(p.va + shift + s.at, s, k) for k, p in enumerate(fix.patterns.values(), 1)
            for s in p.sites.values()]


def originals(fix, shift=0):
    """The site bytes as in the original build (moved by shift: rel32 fields stay the same, as
    their targets moved along)."""
    return [(va, original_bytes(fix, k)[site.at:site.at + site_length(site)])
            for va, site, k in sites(fix, shift)]


def patched(fix, code_va=EXE_CAVE_VA, shift=0):
    """The site bytes with the fix applied and its cave at code_va."""
    out = []
    for va, site, _ in sites(fix, shift):
        if site.patched:
            out.append((va, bytes.fromhex(site.patched.decode())))
            continue
        jump = (b"\xe9" if site.hook else b"\xe8") + struct.pack("<i", code_va + fix.offset - (va + 5))
        out.append((va, jump + b"\xcc" * (site_length(site) - 5)))
    return out


def image(on_disk=(), shift=0, timestamp=TIMESTAMP, skip=()):
    """A noita.exe image with every pattern's original-build bytes, all code moved by shift
    bytes; fixes whose id is in on_disk patched on disk, ids in skip left out."""
    data = bytearray(IMAGE_BYTES)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", data, 0x84, 0x14C, 1, timestamp)
    struct.pack_into("<H", data, 0x94, 0xE0)
    struct.pack_into("<8sIIIIIIHHI", data, SECTION_TABLE, b".text", IMAGE_BYTES - 0x1000, 0x1000,
                     IMAGE_BYTES - 0x1000, 0x400, 0, 0, 0, 0, 0x60000020)
    for fix in fix_list():
        if fix.id.decode() in skip:
            continue
        for k, p in enumerate(fix.patterns.values(), 1):
            at = p.va + shift - IMAGE_BASE
            data[at:at + len(original_bytes(fix, k))] = original_bytes(fix, k)
        if fix.id.decode() in on_disk:
            for va, raw in patched(fix, shift=shift):
                data[va - IMAGE_BASE:va - IMAGE_BASE + len(raw)] = raw
    return data


class FakeMemory:
    def __init__(self, data=None, alloc_at=(EXE_CAVE_VA, EXE_TABLE_VA), base=IMAGE_BASE, marker=None):
        self.image = image() if data is None else bytearray(data)
        self.alloc_at, self.base, self.marker = alloc_at, base, marker
        self.blocks, self.writes, self.allocs, self.sealed = {}, [], [], []

    def locate(self, va, n):
        for start, block in self.blocks.items():
            if start <= va and va + n <= start + len(block):
                return block, va - start
        if self.base <= va and va + n <= self.base + len(self.image):
            return self.image, va - self.base
        raise ValueError(f"unmapped {va:#x}")

    def image_base(self):
        return self.base

    def read(self, va, n):
        block, at = self.locate(int(va), int(n))
        return bytes(block[at:at + int(n)])

    def write(self, va, data):
        block, at = self.locate(int(va), len(data))
        block[at:at + len(data)] = data
        self.writes.append((int(va), bytes(data)))

    def alloc(self, code_bytes, data_bytes):
        self.allocs.append((int(code_bytes), int(data_bytes)))
        code, data = self.alloc_at
        self.blocks[code], self.blocks[data] = bytearray(int(code_bytes)), bytearray(int(data_bytes))
        return code, data

    def seal(self, va, n):
        self.sealed.append((int(va), int(n)))

    def get_marker(self):
        return self.marker

    def set_marker(self, value):
        self.marker = bytes(value)


def run(memory, enabled=None, **options):
    """(message, {fix name: state}, report or None)"""
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    table = lua.table_from({k.encode(): v for k, v in options.items()})
    message, states, report = module.apply(memory, enabled, table)
    return (message.decode(), {k.decode(): v.decode() for k, v in states.items()},
            report.decode() if report else None)


def apply(memory, enabled=None, **options):
    return run(memory, enabled, **options)[:2]

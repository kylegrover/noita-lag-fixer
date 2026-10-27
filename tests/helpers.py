"""A fake noita.exe image and process memory for running files/fixes.lua under Lupa."""
from pathlib import Path
import struct
import sys

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from describe_patches import HOOK_ORIGINALS

IMAGE_BASE, TIMESTAMP = 0x400000, 0x6794EE3C
EXE_CAVE_VA, EXE_TABLE_VA = 0x12E9000, 0x12EA000
CODE_BYTES, DATA_BYTES = 0x268, 0x402020
IMAGE_BYTES = 0x900000  # covers every patched site


def fixes_module():
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    return lua.execute((ROOT / "files" / "fixes.lua").read_text())


def fix_list(module=None):
    return list((module or fixes_module()).FIXES.values())


def originals(fix):
    if fix.sites:
        return [(s[1], bytes.fromhex(s[2].decode())) for s in fix.sites.values()]
    if fix.hook:
        return [(fix.hook.va, HOOK_ORIGINALS[fix.hook.va])]
    return [(fix.call.va, bytes.fromhex(fix.call.original.decode()))]


def patched(fix, code_va=EXE_CAVE_VA):
    """The site bytes with the fix applied and its cave at code_va."""
    if fix.sites:
        return [(s[1], bytes.fromhex(s[3].decode())) for s in fix.sites.values()]
    va = fix.hook.va if fix.hook else fix.call.va
    rel = struct.pack("<i", code_va + fix.offset - (va + 5))
    if fix.hook:
        return [(va, b"\xe9" + rel + b"\xcc" * (fix.hook.length - 5))]
    return [(va, b"\xe8" + rel)]


def image(on_disk=()):
    """The original build's bytes at every site; fixes whose id is in on_disk patched on disk."""
    data = bytearray(IMAGE_BYTES)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<I", data, 0x88, TIMESTAMP)
    for fix in fix_list():
        for va, raw in (patched(fix) if fix.id.decode() in on_disk else originals(fix)):
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
        if IMAGE_BASE <= va and va + n <= IMAGE_BASE + len(self.image):
            return self.image, va - IMAGE_BASE
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


def apply(memory, enabled=None):
    module = fixes_module()
    message, states = module.apply(memory, enabled) if enabled else module.apply(memory)
    return message.decode(), {k.decode(): v.decode() for k, v in states.items()}

"""Run Lag Fixer's search on a noita.exe file and print its scan report. Nothing is written to
the file: the mod "applies" the fixes to a copy in memory.

Usage: uv run tools/scan_exe.py path/to/noita.exe [--other-builds]
"""
from pathlib import Path
import struct
import sys

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class ExeFile:
    """An exe file laid out at its virtual addresses as Windows would load it, as `memory` for
    files/fixes.lua. Allocations go to fresh blocks right after the image."""

    def __init__(self, data):
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        count, opt = struct.unpack_from("<HxxxxxxxxxxxxH", data, pe + 6)
        self.base, size = struct.unpack_from("<I", data, pe + 52)[0], struct.unpack_from("<I", data, pe + 80)[0]
        headers = struct.unpack_from("<I", data, pe + 84)[0]
        self.image = bytearray(size)
        self.image[:headers] = data[:headers]
        for n in range(count):
            vsize, rva, rawsize, rawptr = struct.unpack_from("<IIII", data, pe + 24 + opt + 40 * n + 8)
            raw = data[rawptr:rawptr + min(vsize, rawsize)]
            self.image[rva:rva + len(raw)] = raw
        self.blocks, self.writes, self.marker = {}, [], None
        self.next_alloc = (self.base + size + 0xFFFF) & ~0xFFFF

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
        out = []
        for n in (int(code_bytes), int(data_bytes)):
            self.blocks[self.next_alloc] = bytearray(n)
            out.append(self.next_alloc)
            self.next_alloc = (self.next_alloc + n + 0xFFFF) & ~0xFFFF
        return tuple(out)

    def seal(self, va, n):
        pass

    def get_marker(self):
        return self.marker

    def set_marker(self, value):
        self.marker = bytes(value)


def scan(data, other_builds=False):
    """(status message, scan report, the ExeFile after applying) for exe bytes."""
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    memory = ExeFile(data)
    options = lua.table_from({b"other_builds": other_builds, b"report": True})
    message, _, report = module.apply(memory, None, options)
    return message.decode(), report.decode(), memory


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    print(scan(Path(args[0]).read_bytes(), "--other-builds" in sys.argv)[1], end="")


if __name__ == "__main__":
    main()

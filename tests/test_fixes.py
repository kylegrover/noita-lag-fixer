import struct

import capstone
from lupa.lua51 import LuaRuntime
import pytest

from helpers import (CODE_BYTES, DATA_BYTES, EXE_CAVE_VA, EXE_TABLE_VA, IMAGE_BASE, IMAGE_BYTES, ROOT,
                     FakeMemory, apply, fix_list, image, originals, patched, run, sites)

ALL_IDS = ["bounds", "pixel_scene_dedup", "explosion_angles", "contact_walk", "sprite_stains"]


def disassembler():
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return md


def caves(fixes):
    return [f for f in fixes if f.code]


def test_bounds_replace_flt_min_with_minus_flt_max():
    bounds = fix_list()[0]
    pairs = list(zip(originals(bounds), patched(bounds)))
    assert len(pairs) == 6
    for (_, before), (_, after) in pairs:
        assert before[-4:] == struct.pack("<I", 0x00800000)
        assert after == before[:-4] + struct.pack("<I", 0xFF7FFFFF)


def test_relocation_lists_cover_every_outside_reference():
    md = disassembler()
    lo, hi = EXE_TABLE_VA, EXE_TABLE_VA + DATA_BYTES
    for fix in caves(fix_list()):
        code, cave = bytes.fromhex(fix.code.decode()), EXE_CAVE_VA + fix.offset
        rel, absolute, end = [], [], 0
        for i in md.disasm(code, cave):
            at, end = i.address - cave, i.address + i.size - cave
            ops = i.operands
            if i.size >= 5 and ops and ops[0].type == capstone.x86.X86_OP_IMM and (
                    i.group(capstone.CS_GRP_JUMP) or i.group(capstone.CS_GRP_CALL)):
                if not cave <= ops[0].imm < cave + len(code):
                    rel.append((at + i.size - 4, ops[0].imm))
            for field, size in ((i.disp_offset, i.disp_size), (i.imm_offset, i.imm_size)):
                if field and size == 4 and lo <= struct.unpack_from("<I", code, at + field)[0] < hi:
                    absolute.append(at + field)
        assert end == len(code)
        assert [(r[1], fix.symbols[r[2]].steam) for r in fix.rel.values()] == rel
        assert absolute == list(fix.abs.values())


def test_patterns_contain_the_replaced_bytes():
    for fix in fix_list():
        for p in fix.patterns.values():
            text = p.bytes.decode()
            assert len(text) % 2 == 0 and all(len(text[n:n + 2].strip("?")) in (0, 2) for n in range(0, len(text), 2))
            for site in p.sites.values():
                replaced = text[site.at * 2:]
                if site.patched:
                    assert "??" not in replaced[:len(site.patched)]
                elif site.call:
                    assert replaced.startswith("e8????????")


def test_at_the_on_disk_addresses_writes_exactly_the_on_disk_patch():
    memory = FakeMemory()
    message, states, report = run(memory)
    assert message == "Lag Fixer: 5 fixes applied" and report is None
    assert set(states.values()) == {"original"}
    fixes = fix_list()
    for fix in fixes:
        for va, raw in patched(fix):
            assert memory.read(va, len(raw)) == raw
    code = bytearray(b"\xcc" * CODE_BYTES)  # the caves unrelocated, as an on-disk patch has them
    for fix in caves(fixes):
        raw = bytes.fromhex(fix.code.decode())
        code[fix.offset:fix.offset + len(raw)] = raw
    assert bytes(memory.blocks[EXE_CAVE_VA]) == bytes(code)
    assert memory.allocs == [(CODE_BYTES, DATA_BYTES)] and memory.sealed == [(EXE_CAVE_VA, CODE_BYTES)]
    assert memory.marker == f"{EXE_CAVE_VA:08x}:{EXE_TABLE_VA:08x}".encode()
    assert not any(memory.blocks[EXE_TABLE_VA])  # data starts zeroed
    writes = sorted(memory.writes[1:])
    assert writes == sorted((va, raw) for fix in fixes for va, raw in patched(fix))


def test_elsewhere_branches_keep_their_targets_and_data_moves():
    md = disassembler()
    code_va, data_va = 0x2340000, 0x5670000
    memory = FakeMemory(alloc_at=(code_va, data_va))
    assert apply(memory)[0] == "Lag Fixer: 5 fixes applied"
    moved, shift = bytes(memory.blocks[code_va]), data_va - EXE_TABLE_VA
    for fix in caves(fix_list()):
        cave, raw = EXE_CAVE_VA + fix.offset, bytes.fromhex(fix.code.decode())
        new_cave = code_va + fix.offset
        site_va = sites(fix)[0][0]
        assert next(md.disasm(memory.read(site_va, 5), site_va)).operands[0].imm == new_cave
        old = list(md.disasm(raw, cave))
        new = list(md.disasm(moved[fix.offset:fix.offset + len(raw)], new_cave))
        assert [i.mnemonic for i in old] == [i.mnemonic for i in new]
        for a, b in zip(old, new):
            text = a.op_str
            if a.mnemonic.startswith(("j", "call")) and text.startswith("0x"):
                target = int(text, 16)
                if cave <= target < cave + len(raw):
                    text = hex(target - cave + new_cave)
            for ref in (EXE_TABLE_VA, EXE_TABLE_VA + 0x402010):
                text = text.replace(hex(ref), hex(ref + shift))
            assert b.op_str == text


def test_second_start_in_the_same_process_reuses_the_caves():
    memory = FakeMemory(alloc_at=(0x2340000, 0x5670000))
    apply(memory)
    writes = len(memory.writes)
    message, states = apply(memory)
    assert message == "Lag Fixer: fixes active" and set(states.values()) == {"session"}
    assert len(memory.writes) == writes and len(memory.allocs) == 1


def test_exe_patched_on_disk_is_left_alone():
    memory = FakeMemory(image(on_disk=ALL_IDS))
    assert apply(memory)[0] == "Lag Fixer: noita.exe already has these fixes"
    assert memory.writes == [] and memory.allocs == []


def test_partly_patched_exe_gets_the_rest():
    memory = FakeMemory(image(on_disk=["bounds", "pixel_scene_dedup", "sprite_stains"]))
    message, states = apply(memory)
    assert message == "Lag Fixer: 2 fixes applied (3 already in noita.exe)"
    assert states["bounds"] == "exe" and states["sprite stains"] == "exe"
    assert states["contact walk"] == "original"
    for fix in fix_list():
        for va, raw in patched(fix):
            assert memory.read(va, len(raw)) == raw


def test_turned_off_fixes_are_left_alone():
    memory = FakeMemory()
    message, _ = apply(memory, lambda fix_id: fix_id != b"explosion_angles")
    assert message == "Lag Fixer: 4 fixes applied (1 off)"
    explosions = next(f for f in fix_list() if f.id == b"explosion_angles")
    assert all(memory.read(va, len(raw)) == raw for va, raw in originals(explosions))

    memory = FakeMemory()
    assert apply(memory, lambda fix_id: fix_id == b"bounds")[0] == "Lag Fixer: 1 fix applied (4 off)"
    assert memory.allocs == []  # no added code needed

    memory = FakeMemory()
    assert apply(memory, lambda fix_id: False)[0] == "Lag Fixer: all fixes turned off"
    assert memory.writes == [] and memory.allocs == []


def test_turning_off_cannot_undo_a_fix_already_in_this_process():
    memory = FakeMemory(alloc_at=(0x2340000, 0x5670000))
    apply(memory)
    message, _ = apply(memory, lambda fix_id: fix_id != b"bounds")
    assert message == "Lag Fixer: fixes active (1 off, 1 turned off but active until Noita restarts)"


def bad_byte_addresses():
    fixes = fix_list()
    return [sites(fixes[0])[3][0] + 4, sites(fixes[1])[0][0], sites(fixes[2])[0][0] + 30,
            sites(fixes[3])[0][0] + 105,
            sites(fixes[4])[0][0] + 1,  # in atan2's address: the call goes somewhere else
            fixes[3].patterns[1].va + 2]  # context before the hooked code


@pytest.mark.parametrize("va", bad_byte_addresses())
def test_any_unexpected_byte_writes_nothing(va):
    data = image()
    data[va - IMAGE_BASE] ^= 0x10
    memory = FakeMemory(data)
    message, _, report = run(memory)
    assert message.startswith("Lag Fixer: unexpected code at ") and message.endswith(", nothing changed")
    assert memory.writes == [] and memory.allocs == []
    assert report.splitlines()[1] == "result: " + message


def test_other_build_or_layout_writes_nothing_by_default():
    for memory in (FakeMemory(image(timestamp=0x12345678)), FakeMemory(base=0x10000000)):
        message, _, report = run(memory)
        assert message == ("Lag Fixer: unsupported noita.exe version, nothing changed"
                           " (5 of 5 fixes found, see scan-report.txt)")
        assert memory.writes == [] and memory.allocs == []
        assert "(Lag Fixer was made for 0x6794ee3c at 0x00400000)" in report
    not_pe = FakeMemory(bytearray(IMAGE_BYTES))
    assert run(not_pe)[0] == "Lag Fixer: unsupported noita.exe version, nothing changed"
    half = FakeMemory()  # one of the six bounds sites already changed: not a known state
    va, raw = patched(fix_list()[0])[0]
    half.image[va - IMAGE_BASE:va - IMAGE_BASE + len(raw)] = raw
    assert apply(half)[0] == "Lag Fixer: unexpected code at bounds, nothing changed"
    assert half.writes == []


def test_other_build_with_the_code_moved():
    shift, code_va, data_va = 0x2345, 0x2340000, 0x5670000
    memory = FakeMemory(image(shift=shift, timestamp=0x12345678), alloc_at=(code_va, data_va))
    message, states, report = run(memory, other_builds=True)
    assert message == "Lag Fixer: 5 fixes applied" and set(states.values()) == {"original"}
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    for fix in fix_list(module):
        for va, raw in patched(fix, code_va, shift):
            assert memory.read(va, len(raw)) == raw
        if fix.code:
            symbols = lua.table_from({name: s.steam + shift for name, s in fix.symbols.items()})
            moved = module.relocate(fix, code_va, data_va, symbols)
            assert memory.read(code_va + fix.offset, len(moved)) == moved
    assert "PE timestamp 0x12345678" in report
    assert f"  sqrt at 0x{0x44A410 + shift:08x} (0x0044a410 in the original build)" in report
    assert apply(memory, other_builds=True)[0] == "Lag Fixer: fixes active"


def test_other_build_skips_what_it_cannot_find():
    data = image(shift=0x40, timestamp=1, skip=["contact_walk"])
    explosions = fix_list()[2]
    p = explosions.patterns[1]
    copy = p.va + 0x40 - IMAGE_BASE
    data[0x8F0000:0x8F0000 + len(p.bytes) // 2] = data[copy:copy + len(p.bytes) // 2]  # found twice
    memory = FakeMemory(data, alloc_at=(0x2340000, 0x5670000))
    message, states, report = run(memory, other_builds=True)
    assert message == "Lag Fixer: 3 fixes applied (2 not found in this noita.exe: explosion angles, contact walk)"
    assert states["contact walk"] == states["explosion angles"] == "missing"
    block = bytes(memory.blocks[0x2340000])
    assert block[0:0x200] == b"\xcc" * 0x200  # caves of fixes not found: never jumped to
    assert "  pattern 1 (0x00659835 in the original build): 2+ unpatched, 0 patched" in report
    assert "contact walk: missing" in report

    nothing = FakeMemory(image(timestamp=1, skip=ALL_IDS))
    assert run(nothing, other_builds=True)[0] == "Lag Fixer: none of the fixes found in this noita.exe, nothing changed"


def test_report_on_request_for_the_known_build():
    message, _, report = run(FakeMemory(), report=True)
    lines = report.splitlines()
    assert lines[0] == "Lag Fixer 1.1.0 scan report" and lines[1] == "result: " + message
    assert "(the build Lag Fixer was made for)" in lines[2]
    assert "code section .text at 0x00401000, 0x8ff000 bytes" in lines
    assert "  pattern 1 (0x007246a4 in the original build): 1 unpatched, 0 patched, at 0x007246a4" in lines


def test_find_handles_wildcards_and_section_edges():
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    pattern = module.parse_pattern(b"??aabb??cc")
    code = lua.eval("function(a, b) return {{va = 0x1000, text = a}, {va = 0x2000, text = b}} end")(
        b"\xaa\xbb\x00\xcc" + b"\x01\xaa\xbb\x02\xcc\xaa\xbb", b"\x05\xaa\xbb\x06\xcc")
    assert list(module.find(code, pattern, 5).values()) == [0x1004, 0x2000]
    assert list(module.find(code, pattern, 1).values()) == [0x1004]


def test_ffi_backend_round_trip():
    from lupa.luajit21 import LuaRuntime as LuaJIT
    lua = LuaJIT(unpack_returned_tuples=True, encoding=None)
    source = (ROOT / "files" / "memory.lua").read_text()
    lua.execute(source)  # a second load in the same state must not fail on the cdefs
    memory = lua.execute(source)
    code, data = memory.alloc(CODE_BYTES, DATA_BYTES)
    assert code and data and data % 16 == 0
    memory.write(code, b"\x90\xc3")
    memory.seal(code, CODE_BYTES)
    assert memory.read(code, 3) == b"\x90\xc3\x00"
    memory.write(data + 0x402010, b"abcd")
    assert memory.read(data + 0x40200E, 8) == b"\x00\x00abcd\x00\x00"
    assert memory.image_base() > 0
    memory.set_marker(b"0abc0000:01230000")
    assert memory.get_marker() == b"0abc0000:01230000"


def test_runs_the_same_under_luajit():
    from lupa.luajit21 import LuaRuntime as LuaJIT
    lua = LuaJIT(unpack_returned_tuples=True, encoding=None)
    module = lua.execute((ROOT / "files" / "fixes.lua").read_text())
    options = lua.table_from({b"other_builds": True})
    memory = FakeMemory(image(shift=0x2345, timestamp=1), alloc_at=(0x2340000, 0x5670000))
    assert module.apply(memory, None, options)[0] == b"Lag Fixer: 5 fixes applied"
    reference = FakeMemory(image(shift=0x2345, timestamp=1), alloc_at=(0x2340000, 0x5670000))
    run(reference, other_builds=True)
    assert memory.writes == reference.writes

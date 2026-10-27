import struct

import capstone
import pytest

from helpers import (CODE_BYTES, DATA_BYTES, EXE_CAVE_VA, EXE_TABLE_VA, HOOK_ORIGINALS, ROOT,
                     FakeMemory, apply, fix_list, fixes_module, image, originals, patched)

ALL_IDS = ["bounds", "pixel_scene_dedup", "explosion_angles", "contact_walk", "sprite_stains"]


def disassembler():
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return md


def caves(fixes):
    return [f for f in fixes if f.code]


def test_check_hashes_match_the_listed_originals():
    module = fixes_module()
    for fix in caves(fix_list(module)):
        if fix.hook:
            original = HOOK_ORIGINALS[fix.hook.va]
            assert len(original) == fix.hook.length
            assert module.check_hash(original) == fix.hook.check


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
                    rel.append(at + i.size - 4)
            for field, size in ((i.disp_offset, i.disp_size), (i.imm_offset, i.imm_size)):
                if field and size == 4 and lo <= struct.unpack_from("<I", code, at + field)[0] < hi:
                    absolute.append(at + field)
        assert end == len(code)
        assert rel == list(fix.rel.values()) and absolute == list(fix.abs.values())


def test_at_the_on_disk_addresses_writes_exactly_the_on_disk_patch():
    memory = FakeMemory()
    message, states = apply(memory)
    assert message == "Lag Fixer: 5 fixes applied"
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


def test_elsewhere_branches_keep_their_targets_and_data_moves():
    md = disassembler()
    code_va, data_va = 0x2340000, 0x5670000
    memory = FakeMemory(alloc_at=(code_va, data_va))
    assert apply(memory)[0] == "Lag Fixer: 5 fixes applied"
    moved, shift = bytes(memory.blocks[code_va]), data_va - EXE_TABLE_VA
    for fix in caves(fix_list()):
        cave, raw = EXE_CAVE_VA + fix.offset, bytes.fromhex(fix.code.decode())
        new_cave = code_va + fix.offset
        site_va = fix.hook.va if fix.hook else fix.call.va
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
    memory = FakeMemory(image(on_disk=["bounds", "pixel_scene_dedup"]))
    message, states = apply(memory)
    assert message == "Lag Fixer: 3 fixes applied (2 already in noita.exe)"
    assert states["bounds"] == "exe" and states["sprite stains"] == "original"
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
    sites = [s[1] for f in fixes if f.sites for s in f.sites.values()]
    return [sites[3] + 4, sites[-1], fixes[2].hook.va + 30, fixes[3].hook.va + 105, fixes[4].call.va + 1]


@pytest.mark.parametrize("va", bad_byte_addresses())
def test_any_unexpected_byte_writes_nothing(va):
    data = image()
    data[va - 0x400000] ^= 0x10
    memory = FakeMemory(data)
    message = apply(memory)[0]
    assert message.startswith("Lag Fixer: unexpected code at ") and message.endswith(", nothing changed")
    assert memory.writes == [] and memory.allocs == []


def test_other_build_or_layout_writes_nothing():
    other = image()
    other[0x88] ^= 1  # PE timestamp
    for memory in (FakeMemory(other), FakeMemory(base=0x10000000)):
        assert "nothing changed" in apply(memory)[0]
        assert memory.writes == [] and memory.allocs == []
    half = FakeMemory()  # one of the six bounds sites already changed: not a known state
    bounds = fix_list()[0]
    va, raw = patched(bounds)[0]
    half.image[va - 0x400000:va - 0x400000 + len(raw)] = raw
    assert apply(half)[0] == "Lag Fixer: unexpected code at bounds, nothing changed"
    assert half.writes == []


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

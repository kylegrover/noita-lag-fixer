"""Against the real Steam noita.exe and noita_dev.exe, when installed (skipped otherwise)."""
from pathlib import Path
import struct

import pytest

from describe_patches import site_length
from helpers import TIMESTAMP, fix_list, patched
import make_patterns
import scan_exe

NOITA = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Noita")


def steam_exe():
    """The original Steam build, unpatched (noita_lag_patch.py keeps a backup when patching)."""
    for name in ("noita.exe.unpatched", "noita.exe"):
        path = NOITA / name
        if path.is_file():
            data = path.read_bytes()
            pe = struct.unpack_from("<I", data, 0x3C)[0]
            if struct.unpack_from("<I", data, pe + 8)[0] == TIMESTAMP:
                return data
    pytest.skip("Steam noita.exe (Jan 25 2025) not installed")


def test_finds_and_patches_exactly_the_reviewed_sites():
    message, report, memory = scan_exe.scan(steam_exe())
    assert message == "Lag Fixer: 7 fixes applied", report
    code_va = int(memory.marker.split(b":")[0], 16)
    expected = sorted((va, raw) for fix in fix_list() for va, raw in patched(fix, code_va))
    assert sorted(w for w in memory.writes if w[0] != code_va) == expected


def test_patterns_are_the_generated_ones():
    generated = make_patterns.patterns(make_patterns.Exe(steam_exe()))
    for fix in fix_list():
        found = generated[fix.id.decode()]
        table = [(p.va, p.bytes.decode(), [(s.at, site_length(s), site_kind(s)) for s in p.sites.values()])
                 for p in fix.patterns.values()]
        assert table == [(va, make_patterns.hex_pattern(pattern), sites)
                         for va, pattern, sites, _ in found]
        symbols = {name.decode(): list(s.rel32.values()) for name, s in (fix.symbols or {}).items() if s.rel32}
        assert symbols == (found[0][3] if fix.symbols else {})


def site_kind(site):
    return "hook" if site.hook else "call" if site.call else "bytes"


def test_dev_build_is_a_different_compile():
    dev = NOITA / "noita_dev.exe"
    if not dev.is_file():
        pytest.skip("noita_dev.exe not installed")
    message, report, memory = scan_exe.scan(dev.read_bytes())
    assert message == ("Lag Fixer: unsupported noita.exe version, nothing changed"
                       " (2 of 7 fixes found, see scan-report.txt)")
    assert memory.writes == []
    message, report, memory = scan_exe.scan(dev.read_bytes(), other_builds=True)
    assert message == ("Lag Fixer: 2 fixes applied (5 not found in this noita.exe:"
                       " bounds, explosion angles, contact walk, sprite stains, far rays)")
    assert memory.writes == [(0x90C6DA, bytes.fromhex("660f1f440000")), (0x884495, bytes.fromhex("8b45ec83c30ceb61"))]

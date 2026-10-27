-- Five noita.exe performance fixes, applied to the running game's memory at startup.
-- Build 9dbd52ce (Jan 25 2025) only. PATCHES.txt shows every change as before/after disassembly.
--
-- Every byte that gets replaced is checked first (raw bytes, or a check hash for the two long
-- hooked regions). If anything doesn't match, nothing is written. The added code ("caves") is
-- relocated into memory from `memory.alloc`; the table/slot data starts zeroed. Fixes already
-- present (an exe patched on disk with the same changes, or an earlier start in this process)
-- are skipped. Nothing is undone at runtime: turn a fix off and restart Noita.
--
-- `memory` (files/memory.lua, or a fake in tests) provides image_base(), read(va, n),
-- write(va, bytes), alloc(code_bytes, data_bytes), seal(va, n), get_marker() and set_marker(s).
local Fixes = {}

local IMAGE_BASE, TIMESTAMP = 0x400000, 0x6794EE3C
-- The caves are written for code at 0x12e9000 and data at 0x12ea000 (where an exe patched on disk
-- puts them, right after the image) and relocated from there.
local EXE_CAVE_VA, EXE_TABLE_VA = 0x12E9000, 0x12EA000
local CODE_BYTES, DATA_BYTES = 0x268, 0x402020  -- caves; angle table + 16-byte stains slot
local PREFIX = "Lag Fixer: "

Fixes.FIXES = {
    {   -- Bounding boxes start with max = FLT_MIN instead of -FLT_MAX, so boxes west of / above
        -- the world centre stretch to 0,0: 0x00800000 -> 0xff7fffff at six spots.
        id = "bounds",
        name = "bounds",
        sites = {
            {0x7246B5, "c7423400008000", "c74234ffff7fff"},
            {0x7246BC, "c7423800008000", "c74238ffff7fff"},
            {0xAD0EE2, "c744247000008000", "c7442470ffff7fff"},
            {0xAD0F08, "c744247400008000", "c7442474ffff7fff"},
            {0xAD1CE4, "c744242000008000", "c7442420ffff7fff"},
            {0xAD1D01, "c744242400008000", "c7442424ffff7fff"},
        },
    },
    {   -- LoadPixelScene duplicate check: outer-loop `jb` -> 6-byte NOP (single pass)
        id = "pixel_scene_dedup",
        name = "pixel scene dedup",
        sites = {{0x87F8BA, "0f8273fbffff", "660f1f440000"}},
    },
    {   -- Explosions: cache the per-cell atan2 angle in a 1025 x 1025 table
        id = "explosion_angles",
        name = "explosion angles",
        hook = {va = 0x659846, length = 45, check = "175097da6e1c3310"},
        offset = 0x000,
        code = "f30f2c44244005000200003d00040000777bf30f2c4c242081c10002000081f900040000776769c00104000001c8"
            .. "8b0c8500a02e0185c9740f81f10100c07f660f6ec1e92b0837ff50e8c21316ff0f28d00f57c00f2ed09ff6c444"
            .. "7b19f30f104c2424f30f10442444f30f5ecaf30f5ec2e8ba1216ff58660f7ec181f10100c07f890c8500a02e01"
            .. "e9e60737ffe87e1316ff0f28d00f57c00f2ed09ff6c4447b19f30f104c2420f30f10442440f30f5ecaf30f5ec2"
            .. "e8761216ffe9b40737ff",
        rel = {0x44, 0x4A, 0x72, 0x89, 0x8E, 0xB6, 0xBB},  -- rel32 fields that leave the cave
        abs = {0x31, 0x84},  -- absolute addresses inside the data block
    },
    {   -- Box2D AddPair: walk both bodies' contact lists side by side
        id = "contact_walk",
        name = "contact walk",
        hook = {va = 0x9BD3DC, length = 106, check = "5473fda672b3a600"},
        offset = 0x100,
        code = "8b8ec80000008b44240c8b90c800000085c90f84a500000085d20f849d0000008b44240c390175438b7904395f34"
            .. "751b8b44241439473875128b44241c39473c75098b442418394740747b8b4424143947347517395f3875128b4424"
            .. "1839473c75098b44241c394740745b393275438b7a04395f34751b8b44241439473875128b44241c39473c75098b"
            .. "44241839474074348b4424143947347517395f3875128b44241839473c75098b44241c39474074148b490c8b520c"
            .. "e953ffffff8b7c2414e980426dffe96b436dff",
        rel = {0xC2, 0xC7},
        abs = {},
    },
    {   -- SpriteStains: one-entry memo in front of the per-pixel atan2 call
        id = "sprite_stains",
        name = "sprite stains",
        call = {va = 0xC226D4, original = "e8577c82ff"},
        offset = 0x200,
        code = "660f7ec0660f7eca0f280510c06e01660f7ec139c1751b660f70c039660f7ec139d1750e660f70c039660f7ec166"
            .. "0f6ec1c3660f6ec083ec1089042489542404e8eb1016fff30f11442408c744240c000000000f100c240f290d10c0"
            .. "6e01f30f104c240483c410c3",
        rel = {0x41},
        abs = {0x0B, 0x5A},
    },
}

local function from_hex(hex)
    return (hex:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end))
end

local function le32(value)
    value = value % 4294967296
    local out = {}
    for i = 1, 4 do
        out[i] = string.char(value % 256)
        value = math.floor(value / 256)
    end
    return table.concat(out)
end

local function read_le32(bytes, pos)
    local a, b, c, d = bytes:byte(pos, pos + 3)
    return a + b * 256 + c * 65536 + d * 16777216
end

-- Two small polynomial hashes; only has to tell this build's bytes from another build's.
function Fixes.check_hash(bytes)
    local a, b = 0, 0
    for i = 1, #bytes do
        local c = bytes:byte(i)
        a = (a * 257 + c) % 2147483647
        b = (b * 65599 + c) % 2147483629
    end
    return string.format("%08x%08x", a, b)
end

-- The cave as it must look at code_va, with the data block at data_va.
function Fixes.relocate(fix, code_va, data_va)
    local code = from_hex(fix.code)
    local cave_va, exe_cave_va = code_va + fix.offset, EXE_CAVE_VA + fix.offset
    for _, at in ipairs(fix.rel) do
        local rel = read_le32(code, at + 1)
        if rel >= 2147483648 then rel = rel - 4294967296 end
        local target = exe_cave_va + at + 4 + rel
        code = code:sub(1, at) .. le32(target - (cave_va + at + 4)) .. code:sub(at + 5)
    end
    for _, at in ipairs(fix.abs) do
        local value = read_le32(code, at + 1) - EXE_TABLE_VA + data_va
        code = code:sub(1, at) .. le32(value) .. code:sub(at + 5)
    end
    return code
end

-- Site writes as {va, original check, replacement} for caves at code_va.
local function writes(fix, code_va)
    local out = {}
    if fix.sites then
        for _, site in ipairs(fix.sites) do
            out[#out + 1] = {va = site[1], original = from_hex(site[2]), patched = from_hex(site[3])}
        end
    elseif fix.hook then
        local h = fix.hook
        local jump = "\233" .. le32(code_va + fix.offset - (h.va + 5))
        out[1] = {va = h.va, check = h.check, length = h.length,
                  patched = jump .. string.rep("\204", h.length - 5)}
    else
        local c = fix.call
        out[1] = {va = c.va, original = from_hex(c.original),
                  patched = "\232" .. le32(code_va + fix.offset - (c.va + 5))}
    end
    return out
end

local function matches_original(memory, w)
    local now = memory.read(w.va, #w.patched)
    if w.check then return Fixes.check_hash(now) == w.check end
    return now == w.original
end

-- "original", "exe" (patched on disk), "session" (applied earlier in this process) or "unknown".
local function fix_state(memory, fix, session_code_va)
    -- Byte-only fixes look the same either way; with a marker, call them "session".
    local candidates = {{"exe", EXE_CAVE_VA}}
    if session_code_va then table.insert(candidates, 1, {"session", session_code_va}) end
    local original = true
    for _, w in ipairs(writes(fix, EXE_CAVE_VA)) do
        if not matches_original(memory, w) then original = false end
    end
    if original then return "original" end
    for _, candidate in ipairs(candidates) do
        local all = true
        for _, w in ipairs(writes(fix, candidate[2])) do
            if memory.read(w.va, #w.patched) ~= w.patched then all = false end
        end
        if all then return candidate[1] end
    end
    return "unknown"
end

local function parse_marker(marker)
    if marker == nil then return nil end
    local code, data = string.match(marker, "^(%x%x%x%x%x%x%x%x):(%x%x%x%x%x%x%x%x)$")
    if code == nil then return nil end
    return tonumber(code, 16), tonumber(data, 16)
end

-- Applies the fixes for which enabled(id) is true (all if nil). Returns a one-line status
-- message and a {fix name = state before applying} table.
function Fixes.apply(memory, enabled)
    if memory.image_base() ~= IMAGE_BASE then
        return PREFIX .. "unexpected noita.exe layout, nothing changed", {}
    end
    local header = memory.read(IMAGE_BASE, 0x200)
    local pe = read_le32(header, 0x3C + 1)
    if header:sub(1, 2) ~= "MZ" or pe > 0x1F8 - 8 or header:sub(pe + 1, pe + 4) ~= "PE\0\0"
        or read_le32(header, pe + 8 + 1) ~= TIMESTAMP then
        return PREFIX .. "unsupported noita.exe version, nothing changed", {}
    end

    local session_code, session_data = parse_marker(memory.get_marker())
    local states, todo, unknown = {}, {}, {}
    local counts = {original = 0, exe = 0, session = 0, unknown = 0}
    local off, still_on = 0, 0
    for _, fix in ipairs(Fixes.FIXES) do
        local state = fix_state(memory, fix, session_code)
        states[fix.name] = state
        if enabled ~= nil and not enabled(fix.id) then
            off = off + 1
            if state == "session" then still_on = still_on + 1 end
        else
            counts[state] = counts[state] + 1
            if state == "original" then todo[#todo + 1] = fix end
            if state == "unknown" then unknown[#unknown + 1] = fix.name end
        end
    end
    if #unknown > 0 then
        return PREFIX .. "unsupported noita.exe version, nothing changed ("
            .. table.concat(unknown, ", ") .. ")", states
    end

    local code_va, data_va = session_code, session_data
    for _, fix in ipairs(todo) do
        if fix.code and code_va == nil then
            code_va, data_va = memory.alloc(CODE_BYTES, DATA_BYTES)
            if code_va == nil then
                return PREFIX .. "couldn't allocate memory, nothing changed (" .. tostring(data_va) .. ")", states
            end
            local parts = {}
            for _, f in ipairs(Fixes.FIXES) do
                if f.code then
                    parts[#parts + 1] = string.rep("\204", f.offset - #table.concat(parts))
                    parts[#parts + 1] = Fixes.relocate(f, code_va, data_va)
                end
            end
            local code = table.concat(parts)
            memory.write(code_va, code)
            memory.seal(code_va, #code)
            if memory.read(code_va, #code) ~= code then
                return PREFIX .. "added code didn't verify, nothing changed", states
            end
            memory.set_marker(string.format("%08x:%08x", code_va, data_va))
        end
    end
    local applied = 0
    for _, fix in ipairs(todo) do
        for _, w in ipairs(writes(fix, code_va or EXE_CAVE_VA)) do
            memory.write(w.va, w.patched)
            if memory.read(w.va, #w.patched) ~= w.patched then
                return PREFIX .. "write to " .. fix.name .. " didn't verify; restart Noita", states
            end
        end
        applied = applied + 1
    end

    local message
    if applied > 0 then
        message = string.format("%d %s applied", applied, applied == 1 and "fix" or "fixes")
    elseif counts.exe > 0 and counts.session == 0 then
        message = "noita.exe already has these fixes"
    elseif counts.session > 0 then
        message = "fixes active"
    else
        message = "all fixes turned off"
    end
    local notes = {}
    if counts.exe > 0 and (applied > 0 or counts.session > 0) then
        notes[#notes + 1] = string.format("%d already in noita.exe", counts.exe)
    end
    if off > 0 and applied + counts.exe + counts.session > 0 then notes[#notes + 1] = off .. " off" end
    if still_on > 0 then notes[#notes + 1] = still_on .. " turned off but active until Noita restarts" end
    if #notes > 0 then message = message .. " (" .. table.concat(notes, ", ") .. ")" end
    return PREFIX .. message, states
end

return Fixes

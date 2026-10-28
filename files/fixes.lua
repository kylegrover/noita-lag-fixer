-- Seven noita.exe fixes (five performance, two for far-away freezes and crashes), applied
-- Made for build 9dbd52ce (Jan 25 2025). PATCHES.txt shows every change as before/after disassembly.
--
-- Each fix finds its code by searching noita.exe's code sections for byte patterns: the
-- replaced bytes plus some surrounding code, with ?? for the address fields that move between
-- builds of the same code. A pattern has to match exactly once (on the build above: at exactly
-- the reviewed address) or the fix isn't touched. The added code ("caves") is relocated into
-- memory from `memory.alloc`; the noita.exe addresses it uses (sqrt, atan2, where to jump back)
-- are read from the matched code, the table/slot data starts zeroed. Fixes already present (an
-- exe patched on disk with the same changes, or an earlier start in this process) are skipped.
-- Nothing is undone at runtime: turn a fix off and restart Noita.
--
-- On any other noita.exe nothing is written unless options.other_builds is set or it's one of
-- the CHECKED builds, and apply() also returns a scan report saying what was found.
--
-- `memory` (files/memory.lua, or a fake in tests) provides image_base(), read(va, n),
-- write(va, bytes), alloc(code_bytes, data_bytes), seal(va, n), get_marker() and set_marker(s).
local Fixes = {}

Fixes.VERSION = "1.2.1"
local IMAGE_BASE, TIMESTAMP = 0x400000, 0x6794EE3C
-- Other builds where every fix was found, each at a consistent shift from the build above (GOG,
-- from a player's scan report) or with identical code (Steam beta): fixes apply by pattern
-- without options.other_builds.
local CHECKED = {[0x6794F6B1] = "GOG Jan 25 2025", [0x6794C092] = "Steam beta branch Jan 25 2025"}
-- The caves are written for code at 0x12e9000 and data at 0x12ea000 (where an exe patched on disk
-- puts them, right after the image) and relocated from there.
local EXE_CAVE_VA, EXE_TABLE_VA = 0x12E9000, 0x12EA000
local CODE_BYTES, DATA_BYTES = 0x2D0, 0x402020  -- caves; angle table + 16-byte stains slot
local PREFIX = "Lag Fixer: "

-- patterns: va = where the pattern starts in the build above; sites = what gets replaced, at a
-- byte offset into the pattern: `patched` bytes in place, a `hook` (jump to the cave over that
-- many bytes) or a `call` to the cave. symbols: addresses the cave needs, from the first
-- pattern's match: the target of the rel32 field(s) at those offsets, or the address `at` an
-- offset; steam = the value in the build above. rel/abs: cave offsets of rel32 fields that go to
-- a symbol and of absolute addresses inside the data block.
Fixes.FIXES = {
    {   -- Bounding boxes start with max = FLT_MIN instead of -FLT_MAX, so boxes west of / above
        -- the world centre stretch to 0,0: 0x00800000 -> 0xff7fffff at six spots.
        id = "bounds",
        name = "bounds",
        patterns = {
            {va = 0x7246A4, sites = {{at = 17, patched = "c74234ffff7fff"}, {at = 24, patched = "c74238ffff7fff"}},
             bytes = "0f5bc0c7422cffff7f7fc74230ffff7f7fc7423400008000c7423800008000f30f59c8f30f2cc1894424708b4424"
                .. "44"},
            {va = 0xAD0ED2, sites = {{at = 16, patched = "c7442470ffff7fff"}, {at = 54, patched = "c7442474ffff7fff"}},
             bytes = "c744242cffff7f7fc7442430ffff7f7fc7442470000080008b00894424588b44242c894424348b44243089442438"
                .. "8b4424708944243cc7442474000080008b44247489442440e8????????8b400c"},
            {va = 0xAD1CD1, sites = {{at = 19, patched = "c7442420ffff7fff"}, {at = 48, patched = "c7442424ffff7fff"}},
             bytes = "f30f594c2418c744244cffff7f7f05c39e2600c744242000008000a3????????f30f5ce8c1f810f30f58e125ff7f"
                .. "0000c74424240000800099f7f9f30f1164241cf30f116c24648d4204"},
        },
    },
    {   -- LoadPixelScene duplicate check: outer-loop `jb` -> 6-byte NOP (single pass)
        id = "pixel_scene_dedup",
        name = "pixel scene dedup",
        patterns = {
            {va = 0x87F8A8, sites = {{at = 18, patched = "660f1f440000"}},
             bytes = "89bdb8feffffc1fa058bc2c1e81f03c23bf80f8273fbffff538d8d60ffffffe8????????c745fc00000000"},
        },
    },
    {   -- Explosions: cache the per-cell atan2 angle in a 1025 x 1025 table
        id = "explosion_angles",
        name = "explosion angles",
        patterns = {
            {va = 0x659835, sites = {{at = 17, hook = 45}},
             bytes = "f30f2c0903ca894c2460898c24e4010000e8????????0f28d00f57c00f2ed09ff6c4447b19f30f104c2420f30f10"
                .. "442440f30f5ecaf30f5ec2e8????????f20f108c24ac000000f30f11442458f30f5ac0"},
        },
        symbols = {sqrt = {rel32 = {18}, steam = 0x44A410}, atan2 = {rel32 = {58}, steam = 0x44A330},
                   back = {at = 62, steam = 0x659873}},
        offset = 0x000,
        code = "f30f2c44244005000200003d00040000777bf30f2c4c242081c10002000081f900040000776769c00104000001c8"
            .. "8b0c8500a02e0185c9740f81f10100c07f660f6ec1e92b0837ff50e8c21316ff0f28d00f57c00f2ed09ff6c444"
            .. "7b19f30f104c2424f30f10442444f30f5ecaf30f5ec2e8ba1216ff58660f7ec181f10100c07f890c8500a02e01"
            .. "e9e60737ffe87e1316ff0f28d00f57c00f2ed09ff6c4447b19f30f104c2420f30f10442440f30f5ecaf30f5ec2"
            .. "e8761216ffe9b40737ff",
        rel = {{0x44, "back"}, {0x4A, "sqrt"}, {0x72, "atan2"}, {0x89, "back"}, {0x8E, "sqrt"},
               {0xB6, "atan2"}, {0xBB, "back"}},
        abs = {0x31, 0x84},
    },
    {   -- Box2D AddPair: walk both bodies' contact lists side by side
        id = "contact_walk",
        name = "contact walk",
        patterns = {
            {va = 0x9BD3CB, sites = {{at = 17, hook = 106}},
             bytes = "8b0157538b4004ffd084c00f84????????8bb6c800000085f674608b44240c8d9b00000000390675478b46048b78"
                .. "348b48388b503c8b40403bfb75163b4c241475103b54241c750a3b4424180f84????????3b7c241475143bcb7510"
                .. "3b542418750a3b44241c0f84????????8b44240c8b760c85f675ae8b7c24148b4424108bcb8b54241cff704cff74"
                .. "241c"},
        },
        symbols = {found = {rel32 = {78, 104}, steam = 0x9BD536}, back = {at = 123, steam = 0x9BD446}},
        offset = 0x100,
        code = "8b8ec80000008b44240c8b90c800000085c90f84a500000085d20f849d0000008b44240c390175438b7904395f34"
            .. "751b8b44241439473875128b44241c39473c75098b442418394740747b8b4424143947347517395f3875128b4424"
            .. "1839473c75098b44241c394740745b393275438b7a04395f34751b8b44241439473875128b44241c39473c75098b"
            .. "44241839474074348b4424143947347517395f3875128b44241839473c75098b44241c39474074148b490c8b520c"
            .. "e953ffffff8b7c2414e980426dffe96b436dff",
        rel = {{0xC2, "back"}, {0xC7, "found"}},
        abs = {},
    },
    {   -- SpriteStains: one-entry memo in front of the per-pixel atan2 call
        id = "sprite_stains",
        name = "sprite stains",
        patterns = {
            {va = 0xC226C4, sites = {{at = 16, call = true}},
             bytes = "8b80e4000000f30f104868f30f10406ce8????????03bc2490000000f30f11442420f30f5ac0"},
        },
        symbols = {atan2 = {rel32 = {17}, steam = 0x44A330}},
        offset = 0x200,
        code = "660f7ec0660f7eca0f280510c06e01660f7ec139c1751b660f70c039660f7ec139d1750e660f70c039660f7ec166"
            .. "0f6ec1c3660f6ec083ec1089042489542404e8eb1016fff30f11442408c744240c000000000f100c240f290d10c0"
            .. "6e01f30f104c240483c410c3",
        rel = {{0x41, "atan2"}},
        abs = {0x0B, 0x5A},
    },
    {   -- Far-away fixes. Two pixel-stepping ray functions loop forever past x ~16.7M (floats 2+
        -- apart: x + 1 == x). The step goes through a cave doing the same two adds; if neither x nor
        -- y moved, it moves the longer axis one float step toward the target (ecx/edx are free here).
        id = "far_rays",
        name = "far rays",
        patterns = {
            {va = 0x95CAF1, sites = {{at = 22, call = true}, {at = 27, patched = "660f1f840000000000"}},
             bytes = "f30f1175e80f2ff00f86????????8b5d14f30f2c45d40f28c4f30f58d80f28c5f30f58d0f30f2cf3f30f115ddcf3"
                .. "0f1155e03bf07511"},
            {va = 0x95CD8F, sites = {{at = 22, call = true}, {at = 27, patched = "660f1f840000000000"}},
             bytes = "f30f1175f40f2ff00f86????????8b5d14f30f2c45d40f28c4f30f58d80f28c5f30f58d0f30f2cf3f30f115ddcf3"
                .. "0f1155e03bf07511"},
        },
        offset = 0x270,
        code = "0f28c3f30f58dc0f28caf30f58d50f2ec37a4c754a0f2eca7a457543660f7ee1660f7eea81e1ffffff7f81e2ffff"
            .. "ff7f39d17212660f7ed9660f7ee2e817000000660f6ed9c3660f7ed1660f7eeae805000000660f6ed1c331ca7802"
            .. "41c349c3",
        rel = {},
        abs = {},
    },
    {   -- Far-away fixes. Terrain outlines simplified to nothing far out crash closing the loop (push_back(front())
        -- of an empty vector). Its empty-only branch now skips to the next outline in place.
        id = "far_polygons",
        name = "far polygons",
        patterns = {
            {va = 0x810854, sites = {{at = 17, patched = "8b45ec83c30ceb61"}},
             bytes = "8b04d989028b44d9048942048b5dfceb5f3bca754a8bc22bc1c1f80383f801733e2bcfb8ffffff1fc1f9032bc183"
                .. "f80172752bd78d5901c1fa03b8ffffff1f8bcad1e92bc13bc2730433d2eb0203d13bd38bce0f42d352e8????????"
                .. "8b5dfc8b4e0485c9740a8b0789018b47048941048b45ec83c30c834604088b75f846895dfc8b48048b382bcfb8ab"
                .. "aaaa2a8975f8f7e9"},
        },
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

local function read_le16(bytes, pos)
    local a, b = bytes:byte(pos, pos + 1)
    return a + b * 256
end

-- A hex pattern (?? = any byte) as its fixed runs, searched for by the longest one.
function Fixes.parse_pattern(hex)
    local runs, run, run_at, n = {}, {}, 0, 0
    local function flush()
        if #run > 0 then runs[#runs + 1] = {run_at, table.concat(run)} end
        run = {}
    end
    for pair in hex:gmatch("..") do
        if pair == "??" then
            flush()
        else
            if #run == 0 then run_at = n end
            run[#run + 1] = string.char(tonumber(pair, 16))
        end
        n = n + 1
    end
    flush()
    local anchor = runs[1]
    for _, r in ipairs(runs) do
        if #r[2] > #anchor[2] then anchor = r end
    end
    return {length = n, runs = runs, anchor = anchor}
end

-- Start addresses of up to `limit` matches in the code sections.
function Fixes.find(code, pattern, limit)
    local out, anchor = {}, pattern.anchor
    for _, section in ipairs(code) do
        local text, init = section.text, 1
        while #out < limit do
            local s = string.find(text, anchor[2], init, true)
            if s == nil then break end
            local start = s - anchor[1]
            if start >= 1 and start + pattern.length - 1 <= #text then
                local ok = true
                for _, r in ipairs(pattern.runs) do
                    if text:sub(start + r[1], start + r[1] + #r[2] - 1) ~= r[2] then
                        ok = false
                        break
                    end
                end
                if ok then out[#out + 1] = section.va + start - 1 end
            end
            init = s + 1
        end
    end
    return out
end

local function site_length(site)
    return site.hook or (site.call and 5) or #site.patched / 2
end

-- The pattern as it looks with this fix applied (cave addresses unknown).
local function patched_hex(p)
    local hex = p.bytes
    for _, site in ipairs(p.sites) do
        local new = site.patched
        if site.hook then new = "e9????????" .. string.rep("cc", site.hook - 5) end
        if site.call then new = "e8????????" end
        hex = hex:sub(1, site.at * 2) .. new .. hex:sub(site.at * 2 + #new + 1)
    end
    return hex
end

for _, fix in ipairs(Fixes.FIXES) do
    for _, p in ipairs(fix.patterns) do
        p.original, p.applied = Fixes.parse_pattern(p.bytes), Fixes.parse_pattern(patched_hex(p))
    end
end

-- {timestamp, sections = {{name, va, size}}} for the executable sections, or nil.
local function headers(memory, base)
    local h = memory.read(base, 0x1000)
    if h:sub(1, 2) ~= "MZ" then return nil end
    local pe = read_le32(h, 0x3C + 1)
    if pe > 0x800 or h:sub(pe + 1, pe + 4) ~= "PE\0\0" then return nil end
    local count, optional = read_le16(h, pe + 6 + 1), read_le16(h, pe + 20 + 1)
    local first = pe + 24 + optional
    if count > 64 or first + 40 * count > #h then return nil end
    local out = {timestamp = read_le32(h, pe + 8 + 1), sections = {}}
    for n = 0, count - 1 do
        local at = first + 40 * n
        local characteristics = read_le32(h, at + 36 + 1)
        if math.floor(characteristics / 0x20000000) % 2 == 1 then  -- IMAGE_SCN_MEM_EXECUTE
            out.sections[#out.sections + 1] = {name = (h:sub(at + 1, at + 8):gsub("%z.*", "")),
                                               va = base + read_le32(h, at + 12 + 1),
                                               size = read_le32(h, at + 8 + 1)}
        end
    end
    return out
end

-- The addresses fix.symbols name, read from the code matched at va; nil if they disagree.
local function resolve(memory, fix, va)
    local out = {}
    for name, s in pairs(fix.symbols or {}) do
        if s.at then out[name] = va + s.at end
        for _, at in ipairs(s.rel32 or {}) do
            local target = (va + at + 4 + read_le32(memory.read(va + at, 4), 1)) % 4294967296
            if out[name] ~= nil and out[name] ~= target then return nil end
            out[name] = target
        end
    end
    return out
end

-- The cave as it must look at code_va, with the data block at data_va.
function Fixes.relocate(fix, code_va, data_va, symbols)
    local code = from_hex(fix.code)
    local cave_va = code_va + fix.offset
    for _, r in ipairs(fix.rel) do
        local at = r[1]
        code = code:sub(1, at) .. le32(symbols[r[2]] - (cave_va + at + 4)) .. code:sub(at + 5)
    end
    for _, at in ipairs(fix.abs) do
        local value = read_le32(code, at + 1) - EXE_TABLE_VA + data_va
        code = code:sub(1, at) .. le32(value) .. code:sub(at + 5)
    end
    return code
end

-- Site writes as {va, bytes} for the fix matched at `vas` (one per pattern), caves at code_va.
local function writes(fix, vas, code_va)
    local out = {}
    for k, p in ipairs(fix.patterns) do
        for _, site in ipairs(p.sites) do
            local va = vas[k] + site.at
            local bytes
            if site.patched then
                bytes = from_hex(site.patched)
            else
                bytes = (site.hook and "\233" or "\232") .. le32(code_va + fix.offset - (va + 5))
                if site.hook then bytes = bytes .. string.rep("\204", site.hook - 5) end
            end
            out[#out + 1] = {va = va, bytes = bytes}
        end
    end
    return out
end

-- "session"/"exe" if the jump or call at va goes to this fix's cave, else nil.
local function cave_state(memory, fix, va, known, session_code)
    local target = (va + 5 + read_le32(memory.read(va + 1, 4), 1)) % 4294967296
    if session_code and target == session_code + fix.offset then return "session" end
    if known and target == EXE_CAVE_VA + fix.offset then return "exe" end
    return nil
end

-- Searches for one fix. Returns its state ("original", "exe" = patched on disk, "session" =
-- applied earlier in this process, "unknown" = patched some other way, "missing" = not found)
-- plus the per-pattern search results and, when original, the matched addresses and symbols.
local function scan_fix(memory, code, fix, known, session_code)
    local found, vas, kinds, missing = {}, {}, {}, false
    for k, p in ipairs(fix.patterns) do
        local o, a = Fixes.find(code, p.original, 2), Fixes.find(code, p.applied, 2)
        found[k] = {original = #o, applied = #a}
        if #o == 1 and #a == 1 and o[1] == a[1] then  -- a call site looks the same either way
            kinds[k] = "original"
            for _, site in ipairs(p.sites) do
                if cave_state(memory, fix, o[1] + site.at, known, session_code) then kinds[k] = "applied" end
            end
            vas[k] = o[1]
        elseif #o == 1 and #a == 0 then
            vas[k], kinds[k] = o[1], "original"
        elseif #o == 0 and #a == 1 then
            vas[k], kinds[k] = a[1], "applied"
        else
            missing = true
        end
        found[k].va = vas[k]
    end
    if missing then return "missing", found end
    for k, p in ipairs(fix.patterns) do
        if kinds[k] ~= kinds[1] or (known and vas[k] ~= p.va) then return "unknown", found end
    end
    if kinds[1] == "original" then
        local symbols = resolve(memory, fix, vas[1])
        if symbols == nil then return "unknown", found end
        for name, s in pairs(fix.symbols or {}) do
            if known and symbols[name] ~= s.steam then return "unknown", found end
        end
        return "original", found, vas, symbols
    end
    if not fix.code then return session_code and "session" or "exe", found end
    local state
    for k, p in ipairs(fix.patterns) do
        for _, site in ipairs(p.sites) do
            if not site.patched then  -- in-place bytes matched the applied pattern already
                local this = cave_state(memory, fix, vas[k] + site.at, known, session_code) or "unknown"
                if state ~= nil and state ~= this then return "unknown", found end
                state = this
            end
        end
    end
    return state, found
end

local function parse_marker(marker)
    if marker == nil then return nil end
    local code, data = string.match(marker, "^(%x%x%x%x%x%x%x%x):(%x%x%x%x%x%x%x%x)$")
    if code == nil then return nil end
    return tonumber(code, 16), tonumber(data, 16)
end

local function count_text(n)
    return n >= 2 and "2+" or tostring(n)
end

-- What the search found, for scan-report.txt.
local function report(message, base, h, known, checked, code, scans)
    local lines = {
        "Lag Fixer " .. Fixes.VERSION .. " scan report",
        "result: " .. message,
        string.format("noita.exe: PE timestamp 0x%08x, image base 0x%08x (%s)", h.timestamp, base,
                      known and "the build Lag Fixer was made for"
                          or checked and checked .. ", checked against the build Lag Fixer was made for"
                          or string.format("Lag Fixer was made for 0x%08x at 0x%08x", TIMESTAMP, IMAGE_BASE)),
    }
    for _, s in ipairs(code) do
        lines[#lines + 1] = string.format("code section %s at 0x%08x, 0x%x bytes", s.name, s.va, #s.text)
    end
    for _, fix in ipairs(Fixes.FIXES) do
        local scan = scans[fix.id]
        lines[#lines + 1] = ""
        lines[#lines + 1] = fix.name .. ": " .. scan.state
        for k, p in ipairs(fix.patterns) do
            local r = scan.found[k]
            if r then
                local line = string.format("  pattern %d (0x%08x in the original build): %s unpatched, %s patched",
                                           k, p.va, count_text(r.original), count_text(r.applied))
                if r.va then line = line .. string.format(", at 0x%08x", r.va) end
                if r.va == nil then  -- how common are just the replaced bytes?
                    for _, site in ipairs(p.sites) do
                        local bytes = p.bytes:sub(site.at * 2 + 1, (site.at + site_length(site)) * 2)
                        local n = #Fixes.find(code, Fixes.parse_pattern(bytes), 10)
                        line = line .. string.format("; replaced bytes at +%d alone: %s", site.at,
                                                     n >= 10 and "10+" or tostring(n))
                    end
                end
                lines[#lines + 1] = line
            end
        end
        local names = {}
        for name in pairs(scan.symbols or {}) do names[#names + 1] = name end
        table.sort(names)
        for _, name in ipairs(names) do
            lines[#lines + 1] = string.format("  %s at 0x%08x (0x%08x in the original build)", name,
                                              scan.symbols[name], fix.symbols[name].steam)
        end
    end
    return table.concat(lines, "\n") .. "\n"
end

-- Applies the fixes for which enabled(id) is true (all if nil). options.other_builds allows
-- noita.exe builds other than the one above. Returns a one-line status message, a {fix name =
-- state before applying} table, and a scan report if the build isn't the one above, something
-- didn't match or options.report is set (nil otherwise).
function Fixes.apply(memory, enabled, options)
    options = options or {}
    local base = memory.image_base()
    local h = headers(memory, base)
    if h == nil then return PREFIX .. "unsupported noita.exe version, nothing changed", {}, nil end
    local known = base == IMAGE_BASE and h.timestamp == TIMESTAMP
    local checked = base == IMAGE_BASE and CHECKED[h.timestamp] or nil
    local code = {}
    for _, s in ipairs(h.sections) do
        code[#code + 1] = {name = s.name, va = s.va, text = memory.read(s.va, s.size)}
    end

    local session_code, session_data = parse_marker(memory.get_marker())
    local states, scans, todo, unknown, missing, found = {}, {}, {}, {}, {}, 0
    local counts = {original = 0, exe = 0, session = 0}
    local off, still_on = 0, 0
    for _, fix in ipairs(Fixes.FIXES) do
        local state, matches, vas, symbols = scan_fix(memory, code, fix, known, session_code)
        scans[fix.id] = {state = state, found = matches, vas = vas, symbols = symbols}
        states[fix.name] = state
        if state ~= "missing" and state ~= "unknown" then found = found + 1 end
        if enabled ~= nil and not enabled(fix.id) then
            off = off + 1
            if state == "session" then still_on = still_on + 1 end
        elseif state == "unknown" or (state == "missing" and known) then
            unknown[#unknown + 1] = fix.name
        elseif state == "missing" then
            missing[#missing + 1] = fix.name
        else
            counts[state] = counts[state] + 1
            if state == "original" then todo[#todo + 1] = fix end
        end
    end
    local function done(message)
        local wanted = options.report or not known or #unknown > 0 or #missing > 0
        return PREFIX .. message, states, wanted and report(PREFIX .. message, base, h, known, checked, code, scans) or nil
    end
    if not known and not checked and not options.other_builds then
        return done(string.format("unsupported noita.exe version, nothing changed (%d of %d fixes found,"
                                  .. " see scan-report.txt)", found, #Fixes.FIXES))
    end
    if #unknown > 0 then
        return done("unexpected code at " .. table.concat(unknown, ", ") .. ", nothing changed")
    end

    local code_va, data_va = session_code, session_data
    for _, fix in ipairs(todo) do
        if fix.code and code_va == nil then
            code_va, data_va = memory.alloc(CODE_BYTES, DATA_BYTES)
            if code_va == nil then
                return done("couldn't allocate memory, nothing changed (" .. tostring(data_va) .. ")")
            end
            local parts = {}
            for _, f in ipairs(Fixes.FIXES) do
                if f.code then
                    parts[#parts + 1] = string.rep("\204", f.offset - #table.concat(parts))
                    local symbols = scans[f.id].symbols
                    parts[#parts + 1] = symbols and Fixes.relocate(f, code_va, data_va, symbols)
                        or string.rep("\204", #f.code / 2)  -- not found here: never jumped to
                end
            end
            local cave_code = table.concat(parts)
            memory.write(code_va, cave_code)
            memory.seal(code_va, #cave_code)
            if memory.read(code_va, #cave_code) ~= cave_code then
                return done("added code didn't verify, nothing changed")
            end
            memory.set_marker(string.format("%08x:%08x", code_va, data_va))
        end
    end
    local applied = 0
    for _, fix in ipairs(todo) do
        for _, w in ipairs(writes(fix, scans[fix.id].vas, code_va or EXE_CAVE_VA)) do
            memory.write(w.va, w.bytes)
            if memory.read(w.va, #w.bytes) ~= w.bytes then
                return done("write to " .. fix.name .. " didn't verify; restart Noita")
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
    elseif #missing > 0 then
        message = "none of the fixes found in this noita.exe, nothing changed"
    else
        message = "all fixes turned off"
    end
    local notes = {}
    if counts.exe > 0 and (applied > 0 or counts.session > 0) then
        notes[#notes + 1] = string.format("%d already in noita.exe", counts.exe)
    end
    if #missing > 0 and applied + counts.exe + counts.session > 0 then
        notes[#notes + 1] = #missing .. " not found in this noita.exe: " .. table.concat(missing, ", ")
    end
    if off > 0 and applied + counts.exe + counts.session > 0 then notes[#notes + 1] = off .. " off" end
    if still_on > 0 then notes[#notes + 1] = still_on .. " turned off but active until Noita restarts" end
    if #notes > 0 then message = message .. " (" .. table.concat(notes, ", ") .. ")" end
    return done(message)
end

return Fixes

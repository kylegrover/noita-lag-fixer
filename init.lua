-- Lag Fixer: applies the fixes in files/fixes.lua once at startup (PATCHES.txt lists them).
local MOD = "noita-lag-fixer"
local REPORT = "mods/noita-lag-fixer/scan-report.txt"

local function enabled(id)
    return ModSettingGet(MOD .. "." .. id) ~= false
end

-- What the search found, written for builds the fixes weren't made for or when something
-- didn't match.
local function save_report(report)
    local ok, file = pcall(function() return io.open(REPORT, "w") end)
    if not ok or file == nil then return end
    file:write(report)
    file:close()
end

local function apply()
    local ok, memory = pcall(dofile_once, "mods/noita-lag-fixer/files/memory.lua")
    if not ok then
        return "Lag Fixer: needs unsafe mods allowed in the Mods menu (" .. tostring(memory) .. ")"
    end
    local Fixes = dofile_once("mods/noita-lag-fixer/files/fixes.lua")
    local options = {other_builds = ModSettingGet(MOD .. ".other_builds") == true}
    local done, status, _, report = pcall(Fixes.apply, memory, enabled, options)
    if not done then return "Lag Fixer: error (" .. tostring(status) .. ")" end
    if report then save_report(report) end
    return status
end

local status = apply()
print(status)

function OnPlayerSpawned(player)
    GamePrint(status)
end

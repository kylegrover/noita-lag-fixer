-- Lag Fixer: applies the fixes in files/fixes.lua once at startup (PATCHES.txt lists them).
local MOD = "noita-lag-fixer"

local function enabled(id)
    return ModSettingGet(MOD .. "." .. id) ~= false
end

local function apply()
    local ok, memory = pcall(dofile_once, "mods/noita-lag-fixer/files/memory.lua")
    if not ok then
        return "Lag Fixer: needs unsafe mods allowed in the Mods menu (" .. tostring(memory) .. ")"
    end
    local Fixes = dofile_once("mods/noita-lag-fixer/files/fixes.lua")
    local done, status = pcall(Fixes.apply, memory, enabled)
    if not done then return "Lag Fixer: error (" .. tostring(status) .. ")" end
    return status
end

local status = apply()
print(status)

function OnPlayerSpawned(player)
    GamePrint(status)
end

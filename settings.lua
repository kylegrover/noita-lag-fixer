dofile("data/scripts/lib/mod_settings.lua")

local mod_id = "noita-lag-fixer"
local function fix(id, name, description)
    return {
        id = id,
        ui_name = name,
        ui_description = description .. " Takes effect after restarting Noita.",
        value_default = true,
        scope = MOD_SETTING_SCOPE_RUNTIME_RESTART,
    }
end

mod_settings_version = 1
mod_settings = {
    fix("bounds", "West and sky lag",
        "Huge lag west of or above the world centre (lava, western sky), even while paused."),
    fix("pixel_scene_dedup", "Exploration slowdown",
        "Pixel scene duplicate check that gets slower the more you explore."),
    fix("explosion_angles", "Explosions",
        "Explosion angle per cell cached instead of recomputed."),
    fix("contact_walk", "Physics contacts",
        "Faster Box2D check for existing contacts (terrain touching lots of debris)."),
    fix("sprite_stains", "Sprite stains",
        "Wet/bloody/burning overlays: rotation computed once per sprite, not per pixel."),
}

function ModSettingsUpdate(init_scope)
    mod_settings_update(mod_id, mod_settings, init_scope)
end

function ModSettingsGuiCount()
    return mod_settings_gui_count(mod_id, mod_settings)
end

function ModSettingsGui(gui, in_main_menu)
    mod_settings_gui(mod_id, mod_settings, gui, in_main_menu)
end

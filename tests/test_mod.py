import zipfile

from lupa.lua51 import LuaRuntime

from helpers import ROOT, fix_list
import build_release
import describe_patches

LUA_FILES = ["init.lua", "settings.lua", "files/fixes.lua", "files/memory.lua"]


def test_mod_lua_is_lua51_syntax_and_ascii():
    lua = LuaRuntime(unpack_returned_tuples=True)
    compile_lua = lua.eval("function(source, name) local f, err = loadstring(source, name); assert(f, err) end")
    for name in LUA_FILES:
        source = (ROOT / name).read_bytes().decode("ascii")
        compile_lua(source, name)


def run_init(settings, status="Lag Fixer: 5 fixes applied", caves=None, ffi=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.settings, g.status, g.caves, g.ffi = lua.table_from(settings), status, caves, ffi
    g.memory_source = (ROOT / "files" / "memory.lua").read_text()
    lua.execute("""
        loaded, printed, game_printed, asked = {}, {}, {}, {}
        function dofile_once(path)
            loaded[#loaded + 1] = path
            if path == "mods/noita-lag-fixer/files/memory.lua" then
                if not ffi then return assert(loadstring(memory_source))() end
                return {get_marker = function() return caves end}
            end
            assert(path == "mods/noita-lag-fixer/files/fixes.lua")
            return {apply = function(memory, enabled)
                for _, id in ipairs({"bounds", "pixel_scene_dedup", "explosion_angles",
                                     "contact_walk", "sprite_stains"}) do
                    asked[id] = enabled(id)
                end
                return status
            end}
        end
        function ModSettingGet(key) return settings[key] end
        function GamePrint(line) game_printed[#game_printed + 1] = line end
        function print(line) printed[#printed + 1] = line end
        require = nil; io = nil; os = nil
    """)
    lua.execute((ROOT / "init.lua").read_text())
    lua.execute("OnPlayerSpawned(1)")
    return (list(g.loaded.values()), list(g.printed.values()), list(g.game_printed.values()),
            dict(g.asked.items()))


def test_init_applies_once_and_reports_in_game():
    loaded, printed, game_printed, asked = run_init({"noita-lag-fixer.contact_walk": False})
    assert loaded == ["mods/noita-lag-fixer/files/memory.lua", "mods/noita-lag-fixer/files/fixes.lua"]
    assert printed == game_printed == ["Lag Fixer: 5 fixes applied"]
    assert asked == {"bounds": True, "pixel_scene_dedup": True, "explosion_angles": True,
                     "contact_walk": False, "sprite_stains": True}


def test_init_logs_where_the_added_code_is():
    _, printed, game_printed, _ = run_init({}, caves="0a3c0000:0b000000")
    assert printed == ["Lag Fixer: 5 fixes applied",
                       "Lag Fixer: added code at 0a3c0000:0b000000 (code:data, see PATCHES.txt)"]
    assert game_printed == ["Lag Fixer: 5 fixes applied"]  # the addresses only go to the log


def test_init_without_the_ffi_explains_unsafe_mods():
    loaded, printed, game_printed, _ = run_init({}, ffi=False)
    assert loaded == ["mods/noita-lag-fixer/files/memory.lua"]
    assert len(printed) == 1 and printed[0].startswith("Lag Fixer: needs unsafe mods allowed in the Mods menu (")
    assert game_printed == printed


def test_one_restart_scope_setting_per_fix():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        MOD_SETTING_SCOPE_RUNTIME_RESTART = 1
        function dofile(path) assert(path == "data/scripts/lib/mod_settings.lua") end
        function mod_settings_update(id, settings, scope) updated = {id, settings, scope} end
        function mod_settings_gui_count(id, settings) return #settings end
        function mod_settings_gui(id, settings, gui, in_main_menu) shown = {id, gui, in_main_menu} end
    """)
    lua.execute((ROOT / "settings.lua").read_text())
    lua.execute("ModSettingsUpdate(0); count = ModSettingsGuiCount(); ModSettingsGui(12, true)")
    g = lua.globals()
    assert g.updated[1] == "noita-lag-fixer" and g.updated[3] == 0 and g.count == 5
    assert list(g.shown.values()) == ["noita-lag-fixer", 12, True]
    settings = list(g.updated[2].values())
    assert [s.id for s in settings] == [f.id.decode() for f in fix_list()]
    assert all(s.value_default is True and s.scope == 1 for s in settings)


def test_patch_listing_is_current():
    assert (ROOT / "PATCHES.txt").read_text() == describe_patches.describe()


def test_release_zip_has_the_mod_folder(tmp_path):
    archive = build_release.build(tmp_path)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert names[:3] == ["noita-lag-fixer/mod.xml", "noita-lag-fixer/init.lua", "noita-lag-fixer/settings.lua"]
        assert {"noita-lag-fixer/files/fixes.lua", "noita-lag-fixer/files/memory.lua",
                "noita-lag-fixer/PATCHES.txt", "noita-lag-fixer/README.md"} <= set(names)
        assert not any("tests" in n or "tools" in n for n in names)
        for name in names:
            assert z.read(name) == (ROOT / name.split("/", 1)[1]).read_bytes()


def test_mod_xml():
    xml = (ROOT / "mod.xml").read_text()
    assert 'name="Lag Fixer"' in xml and 'request_no_api_restrictions="1"' in xml

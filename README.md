# Noita Lag Fixer

An unofficial Noita mod (shown in game as "Lag Fixer") that fixes five performance bugs in
`noita.exe`. It patches the running game's memory at startup. The exe on disk and your saves
aren't touched; disable the mod and restart to get the normal game back.

It only works on the current build (Jan 25 2025). On any other version it does nothing.
Not affiliated with or endorsed by Nolla Games.

## What it fixes

1. **West and sky lag.** Bounding boxes start their maximum at the smallest positive float
   instead of the most negative one. Anything entirely west of or above the world centre gets
   a box stretched all the way to 0,0, and the search over that box is huge. This is the lag
   around lava and in the western sky, and it happens even while paused. In a long run, the
   loop went from 81% of Noita's CPU time to 0.2%.
2. **Exploration slowdown.** `LoadPixelScene`'s duplicate check repeats its whole scan once
   per pending pixel scene, so a run gets slower the more you explore. On a long save each call
   went from 17-30 ms to 0.04 ms.
3. **Explosions.** For every cell in the blast area the game computes a square root and an
   angle, but the angle only depends on the cell's offset from the centre. It's now cached.
   Nuke frames went from 77 ms to 28-47 ms.
4. **Physics contacts.** Box2D checks for an existing contact by walking one body's entire
   contact list, which is slow for terrain touching lots of debris. It now walks both bodies'
   lists together and stops at the shorter one. Same result.
5. **Sprite stains.** Wet, bloody and burning overlays recompute the entity's rotation for
   every pixel of the sprite. It's now computed once per sprite. Same result; not measured in
   game yet.

Each fix has its own toggle in Mod Settings (takes effect after restarting Noita).

## Install

1. Download `noita-lag-fixer.zip` from [Releases](../../releases) and unzip it into Noita's
   `mods` folder, so you end up with `Noita\mods\noita-lag-fixer\mod.xml`.
2. In Noita's Mods menu, allow unsafe mods, enable Lag Fixer and restart.
3. Start or continue a run. The message log should say `Lag Fixer: 5 fixes applied`.

It needs unsafe mods because the bugs are in the game's compiled code, which normal Lua mods
can't reach. It uses LuaJIT's FFI only to patch memory (no file or network access). Unsafe mods
can't be uploaded to the Steam Workshop, so it lives here.

## What it changes

[PATCHES.txt](PATCHES.txt) has the disassembly of every changed instruction, before and after,
plus the added code. It's generated from the same table the mod applies
([files/fixes.lua](files/fixes.lua)).

Fixes 1 and 2 change 7 instructions in place. Fixes 3-5 replace an instruction run (or a call)
with a jump to added code. The added code lives in a small block the mod allocates, with a 4 MB
zeroed block for the explosion angle table and the stains cache; its jump targets and data
addresses are adjusted to wherever those blocks end up.

Before writing anything, the mod checks every byte it's about to replace. If anything doesn't
match (a different game version, or another mod already changed that code), it writes nothing.

## Messages

| Message | Meaning |
|---|---|
| `5 fixes applied` | Working. Fewer if some are turned off in Mod Settings. |
| `fixes active` | Already applied earlier in this session (you started a new run). |
| `unsupported noita.exe version, nothing changed` | Different game version. |
| `unexpected code at ..., nothing changed` | The code it patches isn't what it expected, possibly another mod. |
| `needs unsafe mods allowed in the Mods menu` | Unsafe mods are off. |

## Development

```sh
uv run pytest                     # Lua tests under Lupa, against a fake game image
uv run tools/describe_patches.py  # regenerate PATCHES.txt (a test fails if it's out of date)
uv run tools/build_release.py     # dist/noita-lag-fixer.zip
```

The bugs were found by profiling the game and reading its disassembly. Kyle Grover did this
with Claude (Anthropic's AI model), which did much of the reverse engineering and wrote most
of the code. Fixes 1-4 were measured in game before and after.

## License

MIT, see [LICENSE](LICENSE). Noita is (c) Nolla Games.

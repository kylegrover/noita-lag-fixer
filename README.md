# Noita Lag Fixer

An unofficial Noita mod that adds five performance optimizations or bug fixes by patching the running game's memory at startup.

It only works on the current build (Jan 25 2025). On any other version it does nothing. Not affiliated with or endorsed by Nolla Games.

## What it fixes

1. West and Sky Lag: Reduces rendering lag in the west, in the skies, and especially in the western skies. Ever noticed west PWs lag or crash sooner than the east PWs and the sky can get extra laggy? A render calculation's initialization value was leading to oversized bounding boxes in negative game world coordinate, ie anywhere to the left or up from (pretty close to) the starting point. This happens from a few things but particularly the lava in The Work (Sky) would set it off for me, and it happens even while paused. In a long run I tested the loop went from 81% of Noita's CPU time to 0.2%.
2. Exploration Lag: This should fix some of frame drops experienced when entering a new zone on a long run. Pixel scene loading was doing duplicate checks per pending pixel scene, so a run gets slower the more you explore. On a long save I tested each call went from 17-30 ms to 0.04 ms.
3. Explosions: Improves calculation time for all explosions by caching the results for a 1025x1025 cell patch. 
4. Physics Piles: An optimization that you'll only notice around really big piles of Box2D objects such as giant gold piles or debris. Speeds up the contact check by checking both lists at the same time and stopping at the shorter list.
5. Sprite Stains: Small speedup for wet/bloody/burning overlays by sharing rotation calculations between pixels of the sprite to avoid recomputing for each.

Each fix has its own toggle in Mod Settings (takes effect after restarting Noita).

## Install

1. Download `noita-lag-fixer.zip` from [Releases](../../releases) and unzip it into Noita's
   `mods` folder, so you end up with `Noita\mods\noita-lag-fixer\mod.xml`.
2. In Noita's Mods menu, allow unsafe mods, enable Lag Fixer and restart.
3. Start or continue a run. The message log should say `Lag Fixer: 5 fixes applied`.

It needs unsafe mods because the bugs are in the game's compiled code, which normal Lua mods
can't reach. It uses LuaJIT's FFI only to patch memory (no file or network access).

## What it changes

[PATCHES.txt](PATCHES.txt) has the disassembly of every changed instruction, before and after,
plus the added code. It's generated from the same table the mod applies
([files/fixes.lua](files/fixes.lua)).

Fixes 1 and 2 change 7 instructions in place. Fixes 3-5 replace an instruction run (or a call)
with a jump to added code. The added code lives in a small block the mod allocates, with a 4 MB
zeroed block for the explosion angle table and the stains cache. The jump targets and data
addresses are adjusted to wherever those blocks end up.

Before writing anything, the mod checks every byte it's about to replace. If anything doesn't
match (a different game version, or another mod already changed that code), it bails.

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

The bugs were found by profiling my god runs for laggy zones and having an LLM find the hot loops and reading the disassembly.

## License

MIT, see [LICENSE](LICENSE). Noita is (c) Nolla Games.

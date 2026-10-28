# Noita Lag Fixer

An unofficial Noita mod that adds five performance optimizations, plus two fixes for freezes and crashes very far out, by patching the running game's memory at startup.

It's made for the current Steam build (Jan 25 2025). On any other noita.exe it changes nothing by default and writes a report of which fixes it could find (see [Other versions](#other-versions-gog-updates)). Not affiliated with or endorsed by Nolla Games.

## What it fixes

1. West and Sky Lag: Reduces rendering lag in the west, in the skies, and especially in the western skies. Ever noticed west PWs lag or crash sooner than the east PWs and the sky can get extra laggy? A render calculation's initialization value was leading to oversized bounding boxes in negative game world coordinate, ie anywhere to the left or up from (pretty close to) the starting point. This happens from a few things but particularly the lava in The Work (Sky) would set it off for me, and it happens even while paused. In a long run I tested the loop went from 81% of Noita's CPU time to 0.2%.
2. Exploration Lag: This should fix some of frame drops experienced when entering a new zone on a long run. Pixel scene loading was doing duplicate checks per pending pixel scene, so a run gets slower the more you explore. On a long save I tested each call went from 17-30 ms to 0.04 ms.
3. Explosions: Improves calculation time for all explosions by caching the results for a 1025x1025 cell patch. 
4. Physics Piles: An optimization that you'll only notice around really big piles of Box2D objects such as giant gold piles or debris. Speeds up the contact check by checking both lists at the same time and stopping at the shorter list.
5. Sprite Stains: Small speedup for wet/bloody/burning overlays by sharing rotation calculations between pixels of the sprite to avoid recomputing for each.

### Far-away fixes

These only matter if you travel about 470 parallel worlds out or more (x around 17 million and beyond). Closer than that they never kick in, so they do nothing for normal runs. Out there the game's float positions are 2+ pixels apart, which breaks some pixel-by-pixel code.

6. Pixel Scene Freeze: Teleporting to around x = 20 million froze the game forever as soon as a pixel scene loaded. A ray that steps one pixel at a time couldn't move anymore (x + 1 rounds back to x). Now when a step doesn't move, it moves one float step instead, so the ray keeps going.
7. Terrain Crash: Right after that, terrain collision shapes could shrink to nothing and the game crashed closing an empty shape. Empty shapes are now skipped (that branch only ran when the game was about to crash).

Each fix has its own toggle in Mod Settings (takes effect after restarting Noita).

## Install

1. Download `noita-lag-fixer.zip` from [Releases](../../releases) and unzip it into Noita's
   `mods` folder, so you end up with `Noita\mods\noita-lag-fixer\mod.xml`.
2. In Noita's Mods menu, allow unsafe mods, enable Lag Fixer and restart.
3. Start or continue a run. The message log should say `Lag Fixer: 7 fixes applied`.

It needs unsafe mods because the bugs are in the game's compiled code, which normal Lua mods
can't reach. It uses LuaJIT's FFI only to patch memory. The only file it writes is
`scan-report.txt` in its own folder, and only on another noita.exe version or when something
didn't match. No network access.

## What it changes

[PATCHES.txt](PATCHES.txt) has the disassembly of every changed instruction, before and after,
plus the added code. It's generated from the same table the mod applies
([files/fixes.lua](files/fixes.lua)).

Fixes 1, 2 and 7 change instructions in place. Fixes 3-6 replace an instruction run (or a call)
with a jump or call to added code. The added code lives in a small block the mod allocates, with a 4 MB
zeroed block for the explosion angle table and the stains cache. The jump targets and data
addresses are adjusted to wherever those blocks end up.

Each fix finds its code by searching noita.exe for a byte pattern: the bytes it replaces plus
some surrounding code, with wildcards only for addresses that move between builds of the same
code. A fix is applied only if every one of its patterns matches exactly once, and on the
Steam build at exactly the reviewed address. Anything else (another mod already changed that
code, say) and it bails. The addresses the added code needs (sqrt, atan2, where to jump back)
are read from the matched code.

## Other versions (GOG, updates)

The GOG version and Steam's `noitabeta` branch (both also Jan 25 2025) work too: all seven
fixes are found there, so they apply as on Steam (thanks bepoest for testing GOG).

On any other noita.exe (a future update, say), Lag Fixer changes nothing and writes
`mods/noita-lag-fixer/scan-report.txt`, listing which fixes it found and where. Please open
an issue with that file.

If a fix's code is there unchanged (just at different addresses), turning on **Other
noita.exe versions** in Mod Settings applies it. That's untested on those builds, so keep
backups of your saves. Fixes it can't find are skipped: Steam's older-version branches find
6 of 7 (`update_20240812`, all but west and sky lag) and 4 of 7 (`update_20240214`). A build
compiled differently (like Steam's `noita_dev.exe`, where only fixes 2 and 7 match) needs the
fixes redone for it.

## Messages

| Message | Meaning |
|---|---|
| `7 fixes applied` | Working. Fewer if some are turned off in Mod Settings. |
| `fixes active` | Already applied earlier in this session (you started a new run). |
| `unsupported noita.exe version, nothing changed (N of 7 fixes found, ...)` | Different game version, see [Other versions](#other-versions-gog-updates). |
| `... (N not found in this noita.exe: ...)` | Other versions on: those fixes weren't found and were skipped. |
| `unexpected code at ..., nothing changed` | The code it patches isn't what it expected, possibly another mod. |
| `needs unsafe mods allowed in the Mods menu` | Unsafe mods are off. |

## Development

```sh
uv run pytest                     # Lua tests under Lupa, against a fake game image
uv run tools/describe_patches.py  # regenerate PATCHES.txt (a test fails if it's out of date)
uv run tools/build_release.py     # dist/noita-lag-fixer.zip
uv run tools/scan_exe.py path/to/noita.exe [--other-builds]  # scan report for an exe file, offline
uv run tools/make_patterns.py     # the search patterns, from the Steam noita.exe
```

With Noita installed, `tests/test_real_exe.py` also checks the patterns against the real
`noita.exe` and `noita_dev.exe`.

The bugs were found by profiling my god runs for laggy zones and having an LLM find the hot loops and reading the disassembly.

## License

MIT, see [LICENSE](LICENSE). Noita is (c) Nolla Games.

# Noita Lag Fixer

An unofficial Noita mod ("Lag Fixer" in game) that fixes five performance bugs in
`noita.exe`. It changes the running game's memory at startup. The exe on disk and your saves
are never touched, and turning the mod off and restarting gives you the normal game.

Only for the current build (Jan 25 2025). On any other version it changes nothing and says so.
Not made or endorsed by Nolla Games.

## What it fixes

| # | Setting | Bug | Measured |
|---|---|---|---|
| 1 | West and sky lag | Bounding boxes start their maximum at the smallest *positive* float instead of the most negative one. Anything entirely west of or above the world centre gets a box stretched to 0,0, and the region search over it gets huge. This is the lava / western sky lag, and it continues while paused. | That loop went from 81% of Noita's CPU (94% paused) to 0.2% in a long run; west now costs the same as east. |
| 2 | Exploration slowdown | `LoadPixelScene`'s duplicate check repeats its whole scan once per pending pixel scene, so long runs get slower the more you explore. | 17-30 ms per call -> 0.04 ms on a long save. |
| 3 | Explosions | Explosions compute sqrt + atan2 for every cell of the blast square, but the angle only depends on the cell's offset. It's now cached in a table. | Nuke frames 77 ms -> 28-47 ms. |
| 4 | Physics contacts | Box2D's "is there already a contact between these two" check walks one body's whole contact list (bad for terrain touching lots of debris). It now walks both bodies' lists side by side and stops at the shorter. Same answer. | The walk disappeared from profiles. |
| 5 | Sprite stains | Wet / bloody / burning overlays recompute the entity's rotation with atan2 for every pixel of the sprite. It's now computed once per sprite. Same result. | About 75% of the stains system's time in profiles; not yet measured in game. |

Each fix can be turned off on its own in Mod Settings (takes effect after restarting Noita).

## Install

1. Download `noita-lag-fixer.zip` from [Releases](../../releases) and unzip it into Noita's
   `mods` folder, so you have `...\steamapps\common\Noita\mods\noita-lag-fixer\mod.xml`.
   (Or `git clone` this repo into `mods`.)
2. Start Noita, open **Mods**, allow unsafe mods, enable **Lag Fixer** and restart when asked.
3. Start or continue a run. The log in the bottom left says `Lag Fixer: 5 fixes applied`.

**Why unsafe:** the bugs are in the game's compiled code, which normal Lua mods can't reach.
The mod uses LuaJIT's FFI to write to the game's memory, and nothing else (no files, no
network). This is also why it can't be on the Steam Workshop.

## What exactly changes

[PATCHES.txt](PATCHES.txt) lists every changed instruction, before and after, and the full
disassembly of the added code, generated from the same table the mod applies
([files/fixes.lua](files/fixes.lua)). In short:

- Fixes 1 and 2 change 7 instructions in place (6 immediates, 1 jump -> NOP).
- Fixes 3-5 replace an instruction run (or a call) with a jump to added code. The added code
  goes into a small block the mod allocates (0x268 bytes, made execute/read-only), plus a
  4 MB zeroed data block for the explosion angle table and the stains memo. Jump targets
  and data addresses in it are adjusted for wherever it was allocated. `logger.txt` gets a
  `Lag Fixer: added code at ...` line with the addresses.

Before writing anything, every byte it replaces is checked against this build (the two long
hooked regions by check hash). If anything differs, nothing is written. Fixes already present
(from an earlier start in the same process, or an exe patched on disk with the same changes)
are skipped.

## Messages

| Message | Meaning |
|---|---|
| `5 fixes applied` | Working. |
| `fixes active` | Already applied earlier in this session (new run). |
| `unsupported noita.exe version, nothing changed` | Different game version; the mod did nothing. |
| `needs unsafe mods allowed in the Mods menu` | Unsafe mods are off. |
| `noita.exe already has these fixes` | The exe was patched on disk with the same changes. |

## Development

```sh
uv run pytest                     # Lua under Lupa (Lua 5.1 + LuaJIT), fake game memory, capstone
uv run tools/describe_patches.py  # regenerate PATCHES.txt (a test fails if it's stale)
uv run tools/build_release.py     # dist/noita-lag-fixer.zip
```

The tests check that at the exe-patch addresses the mod writes exactly the on-disk patch's
bytes, that every jump in the relocated code still lands on the same target, that the
relocation lists cover every outside reference, and that any unexpected byte means no writes.

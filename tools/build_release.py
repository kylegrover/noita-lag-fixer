"""Write dist/noita-lag-fixer.zip: the mod folder as players install it.

Contains only what the mod needs plus the docs (mod.xml, init.lua, settings.lua, files/*.lua,
PATCHES.txt, README.md, LICENSE if present), under noita-lag-fixer/. Usage:
uv run tools/build_release.py
"""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MOD_ID = "noita-lag-fixer"


def release_files(root=ROOT):
    names = ["mod.xml", "init.lua", "settings.lua"]
    names += [f"files/{p.name}" for p in sorted((root / "files").glob("*.lua"))]
    names += [n for n in ("PATCHES.txt", "README.md", "LICENSE") if (root / n).is_file()]
    return names


def build(dist, root=ROOT):
    dist.mkdir(parents=True, exist_ok=True)
    archive = dist / f"{MOD_ID}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in release_files(root):
            data = (root / name).read_bytes()
            data.decode("ascii")  # keep Noita's Lua/XML loaders on plain ASCII
            z.writestr(f"{MOD_ID}/{name}", data)
    return archive


if __name__ == "__main__":
    print(f"-> {build(ROOT / 'dist')}")

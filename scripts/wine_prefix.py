#!/usr/bin/env python3
"""Create the Wine prefix and keep Halo 2 files outside it."""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

MCC_REL = Path("drive_c") / "Program Files (x86)" / "Steam" / "steamapps" / "common" / "Halo The Master Chief Collection"
GAME_FILES_REL = Path("games") / "Halo The Master Chief Collection"
DXVK_ARCHIVE = "dxvk-macOS-async-v1.10.3-20230507-repack.tar.gz"
DXVK_URL = "https://github.com/Gcenx/DXVK-macOS/releases/download/v1.10.3-20230507-repack/" + DXVK_ARCHIVE
DXVK_SHA256 = "acd1520ad105d8ef124a09c8e11a259a5dc8bdc565ad18e0e52693f9807b2477"
DXVK_DIR = "dxvk-macOS-async-v1.10.3-20230507-repack"


def game_paths(base):
    base = Path(base).resolve()
    return base / GAME_FILES_REL, base / "prefix-wine" / MCC_REL


def ensure_game_files_link(base):
    """Move legacy MCC files once, then ensure Wine's expected path is a symlink."""
    base = Path(base).resolve()
    prefix = base / "prefix-wine"
    if prefix.is_symlink():
        raise RuntimeError(f"The Wine prefix path is a symlink; refusing to change it: {prefix}")
    game_files, link = game_paths(base)
    if link.is_symlink():
        if link.resolve() != game_files:
            raise RuntimeError(f"The MCC symlink points somewhere unexpected: {link}")
        game_files.mkdir(parents=True, exist_ok=True)
        return game_files

    if link.exists():
        if game_files.exists():
            if not game_files.is_dir():
                raise RuntimeError(f"The separate MCC path isn't a directory: {game_files}")
            if any(game_files.iterdir()) and any(link.iterdir()):
                raise RuntimeError("Both the Wine prefix and separate game folder contain MCC files; refusing to merge them.")
            if not any(game_files.iterdir()):
                shutil.rmtree(game_files)
                game_files.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(link), str(game_files))
            else:
                shutil.rmtree(link)
        else:
            game_files.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(link), str(game_files))

    game_files.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(game_files, target_is_directory=True)
    return game_files


def _wine_paths(base):
    base = Path(base).resolve()
    prefix = base / "prefix-wine"
    wine_bin = base / "wine" / "Wine Staging.app" / "Contents" / "Resources" / "wine" / "bin"
    return prefix, wine_bin / "wine", wine_bin / "wineserver"


def _wine_env(prefix):
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG="-all", WINEDLLOVERRIDES="mscoree,mshtml=")
    env.pop("DYLD_INSERT_LIBRARIES", None)
    return env


def _run(command, env, runner, check=True):
    try:
        return runner(command, env=env, capture_output=True, text=True, timeout=180, check=check)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(detail or f"{Path(command[0]).name} failed") from e
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(str(e)) from e


def _dxvk_files(base):
    downloads = Path(base) / "downloads"
    extracted = downloads / DXVK_DIR / "x64"
    dlls = {name: extracted / name for name in ("d3d10core.dll", "d3d11.dll")}
    if all(path.is_file() and path.stat().st_size > 0 for path in dlls.values()):
        return dlls

    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / DXVK_ARCHIVE
    digest = hashlib.sha256(archive.read_bytes()).hexdigest() if archive.is_file() else ""
    if digest != DXVK_SHA256:
        temporary = archive.with_suffix(archive.suffix + ".part")
        try:
            request = urllib.request.Request(DXVK_URL, headers={"User-Agent": "project-gravemind-mac-port"})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != DXVK_SHA256:
                raise RuntimeError("The DXVK download didn't match its checksum.")
            os.replace(temporary, archive)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    extracted.mkdir(parents=True, exist_ok=True)
    members = {f"x64/{name}": name for name in dlls}
    found = set()
    try:
        with tarfile.open(archive, "r:gz") as package:
            for member in package.getmembers():
                name = next((name for suffix, name in members.items() if member.name.endswith("/" + suffix)), None)
                if name is None or not member.isfile():
                    continue
                source = package.extractfile(member)
                if source is None:
                    continue
                dlls[name].write_bytes(source.read())
                found.add(name)
    except (OSError, tarfile.TarError) as e:
        raise RuntimeError(f"The cached DXVK archive couldn't be read ({e}).") from e
    if found != set(dlls):
        raise RuntimeError("The DXVK archive is missing required Windows libraries.")
    return dlls


def _install_dxvk(base, prefix, files=None):
    system32 = prefix / "drive_c" / "windows" / "system32"
    marker = Path(base) / ".installed" / "dxvk"
    dll = system32 / "d3d11.dll"
    current = marker.read_text().strip() if marker.is_file() else ""
    if current == DXVK_ARCHIVE and dll.is_file() and dll.stat().st_size >= 1_000_000:
        return
    files = files or _dxvk_files(base)
    system32.mkdir(parents=True, exist_ok=True)
    shutil.copy2(files["d3d10core.dll"], system32 / "d3d10core.dll")
    shutil.copy2(files["d3d11.dll"], dll)
    (system32 / "d3d11_dxvk.dll").unlink(missing_ok=True)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(DXVK_ARCHIVE + "\n")


def prepare_prefix(base, rebuild=False, install_dxvk=False, runner=subprocess.run):
    base = Path(base).resolve()
    prefix, wine, wineserver = _wine_paths(base)
    if prefix.is_symlink():
        raise RuntimeError(f"The Wine prefix path is a symlink; refusing to replace it: {prefix}")
    game_files = ensure_game_files_link(base)

    dxvk = _dxvk_files(base) if rebuild and install_dxvk else None
    if rebuild:
        env = _wine_env(prefix)
        if wineserver.is_file():
            _run([str(wineserver), "-k"], env, runner, check=False)
            _run([str(wineserver), "-w"], env, runner)
        _, link = game_paths(base)
        if link.is_symlink():
            if link.resolve() != game_files:
                raise RuntimeError(f"The MCC symlink points somewhere unexpected: {link}")
            link.unlink()
        if prefix.exists():
            shutil.rmtree(prefix)

    if not wine.is_file():
        raise RuntimeError("Wine isn't installed. Re-run the installer before rebuilding its prefix.")
    prefix.mkdir(parents=True, exist_ok=True)
    env = _wine_env(prefix)
    system_reg = prefix / "system.reg"
    if not system_reg.is_file():
        _run([str(wine), "wineboot", "-i"], env, runner)
        _run([str(wineserver), "-w"], env, runner)

    if '"DisableHidraw"=dword:00000001' not in (system_reg.read_text(errors="ignore") if system_reg.is_file() else ""):
        _run([str(wine), "reg", "add", r"HKLM\System\CurrentControlSet\Services\winebus",
              "/v", "DisableHidraw", "/t", "REG_DWORD", "/d", "1", "/f"], env, runner)
        _run([str(wineserver), "-w"], env, runner)

    users = prefix / "drive_c" / "users"
    if users.is_dir():
        for documents in users.glob("*/Documents"):
            if documents.is_symlink():
                documents.unlink()
                documents.mkdir(parents=True, exist_ok=True)

    ensure_game_files_link(base)
    if install_dxvk:
        _install_dxvk(base, prefix, dxvk)
    return "ok"


def rebuild_prefix(base):
    return prepare_prefix(base, rebuild=True, install_dxvk=True)


def main(argv):
    if len(argv) != 2 or argv[1] not in ("prepare", "rebuild"):
        print("Usage: wine_prefix.py prepare|rebuild")
        return 2
    base = Path(os.environ.get("RECLAIMER_HOME", Path.home() / "Games" / "ProjectGravemind"))
    try:
        prepare_prefix(base, rebuild=argv[1] == "rebuild", install_dxvk=argv[1] == "rebuild")
        print("ok")
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

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
GAME_FILES_REL = Path("game") / "Halo The Master Chief Collection"
PREVIOUS_GAME_FILES_REL = Path("games") / "Halo The Master Chief Collection"
PROFILE_REL = Path("user-data") / "Project Gravemind"
WORKSHOP_REL = Path("game") / "workshop"
PREVIOUS_WORKSHOP_REL = Path("games") / "workshop"
GRAVEMIND_LOGS_REL = Path("logs") / "appdata-gravemind"
DXVK_ARCHIVE = "dxvk-macOS-async-v1.10.3-20230507-repack.tar.gz"
DXVK_URL = "https://github.com/Gcenx/DXVK-macOS/releases/download/v1.10.3-20230507-repack/" + DXVK_ARCHIVE
DXVK_SHA256 = "acd1520ad105d8ef124a09c8e11a259a5dc8bdc565ad18e0e52693f9807b2477"
DXVK_DIR = "dxvk-macOS-async-v1.10.3-20230507-repack"


def game_paths(base):
    base = Path(base).resolve()
    return base / GAME_FILES_REL, base / "prefix-wine" / MCC_REL


def _move_game_files(sources, destination):
    nonempty = []
    for source in sources:
        if not source.exists():
            continue
        if not source.is_dir():
            raise RuntimeError(f"An MCC path isn't a directory: {source}")
        if any(source.iterdir()):
            nonempty.append(source)
    if len(nonempty) > 1:
        raise RuntimeError("Multiple MCC folders contain files; refusing to merge them.")
    if destination.exists() and not destination.is_dir():
        raise RuntimeError(f"The separate MCC path isn't a directory: {destination}")
    destination_has_files = destination.is_dir() and any(destination.iterdir())
    if destination_has_files and nonempty:
        raise RuntimeError("Both the old and new game folders contain MCC files; refusing to merge them.")

    if nonempty:
        source = nonempty[0]
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    for source in sources:
        if source != destination and source.exists() and source.is_dir() and not any(source.iterdir()):
            shutil.rmtree(source)


def _remove_empty_previous_parent(base):
    try:
        (Path(base) / PREVIOUS_GAME_FILES_REL.parent).rmdir()
    except OSError:
        pass


def ensure_game_files_link(base):
    """Move legacy MCC files once, then ensure Wine's expected path is a symlink."""
    base = Path(base).resolve()
    prefix = base / "prefix-wine"
    if prefix.is_symlink():
        raise RuntimeError(f"The Wine prefix path is a symlink; refusing to change it: {prefix}")
    game_files, link = game_paths(base)
    previous_game_files = base / PREVIOUS_GAME_FILES_REL
    if link.is_symlink():
        target = link.resolve(strict=False)
        if target == game_files.resolve(strict=False):
            game_files.mkdir(parents=True, exist_ok=True)
            _remove_empty_previous_parent(base)
            return game_files
        if target != previous_game_files.resolve(strict=False):
            raise RuntimeError(f"The MCC symlink points somewhere unexpected: {link}")
        link.unlink()

    sources = [path for path in (link, previous_game_files) if path.exists()]
    _move_game_files(sources, game_files)
    game_files.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(game_files, target_is_directory=True)
    _remove_empty_previous_parent(base)
    return game_files


def _ensure_directory_links(sources, destination, label):
    destination = Path(destination)
    sources = [Path(source) for source in sources]
    destination_resolved = destination.resolve(strict=False)
    if destination.is_symlink():
        raise RuntimeError(f"The external {label} path is a symlink; refusing to change it: {destination}")

    nonempty = []
    for source in sources:
        if source.is_symlink():
            if source.resolve(strict=False) != destination_resolved:
                raise RuntimeError(f"The {label} symlink points somewhere unexpected: {source}")
        elif source.exists():
            if not source.is_dir():
                raise RuntimeError(f"The {label} path isn't a directory: {source}")
            if _directory_has_data(source):
                nonempty.append(source)

    if len(nonempty) > 1:
        raise RuntimeError(f"Multiple {label} folders contain files; refusing to merge them.")
    if destination.exists() and not destination.is_dir():
        raise RuntimeError(f"The external {label} path isn't a directory: {destination}")
    destination_has_files = destination.is_dir() and _directory_has_data(destination)
    if destination_has_files and nonempty:
        raise RuntimeError(f"Both the old and new {label} folders contain files; refusing to merge them.")

    if nonempty:
        source = nonempty[0]
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    else:
        destination.mkdir(parents=True, exist_ok=True)

    for source in sources:
        if source.is_symlink():
            continue
        if source.exists():
            source.rmdir()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.symlink_to(destination, target_is_directory=True)


def _directory_has_data(path):
    return any(item.is_file() or item.is_symlink() for item in path.rglob("*"))


def ensure_user_data_links(base):
    """Keep the game profile, Workshop store, and Gravemind logs outside rebuildable Wine state."""
    base = Path(base).resolve()
    prefix = base / "prefix-wine"
    users = prefix / "drive_c" / "users"
    user_dirs = []
    if users.is_dir():
        user_dirs = [user for user in users.iterdir()
                     if user.is_dir() and not user.is_symlink()
                     and user.name.lower() not in {"public", "default", "default user", "all users"}]

    profile_links = [user / "Documents" / "My Games" / "Project Gravemind" for user in user_dirs]
    workshop_link = (prefix / "drive_c" / "Program Files (x86)" / "Steam" / "steamapps" / "workshop")
    logs_links = [user / "AppData" / "Local" / "Project Gravemind" / "logs" for user in user_dirs]
    _ensure_directory_links(profile_links, base / PROFILE_REL, "Gravemind profile")
    _migrate_previous_workshop(base, workshop_link)
    _ensure_directory_links([workshop_link], base / WORKSHOP_REL, "Workshop")
    _ensure_directory_links(logs_links, base / GRAVEMIND_LOGS_REL, "Gravemind logs")


def _migrate_previous_workshop(base, prefix_link):
    previous = Path(base) / PREVIOUS_WORKSHOP_REL
    destination = Path(base) / WORKSHOP_REL
    if previous.is_symlink():
        raise RuntimeError(f"The previous Workshop path is a symlink; refusing to change it: {previous}")
    if not previous.exists():
        return
    if not previous.is_dir():
        raise RuntimeError(f"The previous Workshop path isn't a directory: {previous}")

    prefix_targets_previous = prefix_link.is_symlink() and prefix_link.resolve(strict=False) == previous.resolve()
    if prefix_link.is_symlink() and not prefix_targets_previous and prefix_link.resolve(strict=False) != destination.resolve(strict=False):
        raise RuntimeError(f"The Workshop symlink points somewhere unexpected: {prefix_link}")

    previous_has_data = _directory_has_data(previous)
    destination_has_data = destination.is_dir() and _directory_has_data(destination)
    if previous_has_data and destination_has_data:
        raise RuntimeError("Both the previous and new Workshop folders contain files; refusing to merge them.")

    if prefix_targets_previous:
        prefix_link.unlink()
    if previous_has_data:
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(previous), str(destination))
    else:
        shutil.rmtree(previous)


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
    ensure_user_data_links(base)

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

    ensure_user_data_links(base)
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

#!/usr/bin/env python3
"""The launcher window's Gravemind tools, one command per action.

    controller-check   "stuck" if macOS's game controller service is stuck
    audio-check        the current output and whether it is muted or virtual
    crash-check        "crash: <plain explanation>" if the last game log shows a crash, else "ok"
    force-quit         stop this install's Gravemind process, Wine, and wineserver
    report             zip logs, Gravemind version, and Halo 2 install state to the Desktop
    games              Halo 2 installed state and size, MCC size, and free disk space
    add-game halo2     download Halo 2 from the player's Steam copy using QR sign-in
    repair-game halo2  check installed Halo 2 files against Steam
    repair             the same Halo 2 file check
    remove-game halo2  delete Halo 2 files (MCC shared files stay)
    uninstall          remove this app and install folder

Each prints "ok" (or its result) last, or "error: <plain reason>".
"""
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HOME = Path.home()
BASE = Path(os.environ.get("RECLAIMER_HOME", HOME / "Games" / "ProjectGravemind"))
GAME = BASE / "game"
LOGS = BASE / "logs"
STEAMAPPS = BASE / "prefix-wine" / "drive_c" / "Program Files (x86)" / "Steam" / "steamapps"
WORKSHOP = STEAMAPPS / "workshop" / "content" / "976730"
MCC_DIR = STEAMAPPS / "common" / "Halo The Master Chief Collection"
APP = Path(os.environ.get("RECLAIMER_APP_PATH")
           or Path(os.environ.get("RECLAIMER_APPS_DIR", HOME / "Applications")) / "Project Gravemind.app")
DESKTOP = Path(os.environ.get("RECLAIMER_DESKTOP", HOME / "Desktop"))
# How long the Forge asset library may write nothing before startup is called stalled. The first build takes about a
# minute on the hardware it was tuned for; three minutes of no writes means it is not going to finish on its own.
try:
    FORGE_STALL_SECONDS = int(os.environ.get("RECLAIMER_STALL_SECONDS") or 180)
except ValueError:  # (a hand-set override shouldn't stop the Tools menu working)
    FORGE_STALL_SECONDS = 180


def say(line):
    print(line, flush=True)


# game_process.py from this install: the one rule for which running processes are this installation's game.
_spec = importlib.util.spec_from_file_location("game_process", Path(__file__).resolve().parent / "game_process.py")
game_process = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(game_process)
def game_running():
    return game_process.running(BASE)


def helper():
    """Load the Steam download helper from this install."""
    if "workshop_helper" not in sys.modules:
        spec = importlib.util.spec_from_file_location("workshop_helper", GAME / "workshop_helper.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["workshop_helper"] = mod
    return sys.modules["workshop_helper"]


def gamecontrollerd_state():
    """The process state of macOS's game controller service (e.g. "Ss"), or None when it isn't running."""
    ps = subprocess.run(["/bin/ps", "-axo", "stat=,comm="], capture_output=True, text=True).stdout
    for line in ps.splitlines():
        state, _, command = line.strip().partition(" ")
        if command.strip() == "/usr/libexec/gamecontrollerd":
            return state
    return None


def controller_check():
    """macOS's gamecontrollerd can get stuck in the kernel (state U, for good). Every app that looks for controllers
    then hangs, Wine's included, so the game never sees one although Bluetooth shows it connected. Only a restart
    clears it. A moment of waiting is normal, so it counts only if the service is stuck on every look."""
    for i in range(4):
        if i:
            time.sleep(0.5)
        if "U" not in (gamecontrollerd_state() or ""):
            return "ok"
    return "stuck"


def output_devices():
    """macOS's sound output devices: [(name, is the default output, transport)], or [] when it can't tell."""
    try:
        out = subprocess.run(["/usr/sbin/system_profiler", "SPAudioDataType", "-json"], capture_output=True,
                             text=True, timeout=20).stdout
        items = [d for group in json.loads(out).get("SPAudioDataType", []) for d in group.get("_items", [])]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [(" ".join(str(d.get("_name", "")).split()), d.get("coreaudio_default_audio_output_device") == "spaudio_yes",
             d.get("coreaudio_device_transport", ""))
            for d in items if d.get("coreaudio_device_output")]


def output_muted():
    """Whether the Mac's sound output is muted, or None when it can't tell."""
    try:
        out = subprocess.run(["/usr/bin/osascript", "-e", "output muted of (get volume settings)"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {"true": True, "false": False}.get(out)


def audio_check():
    """Where the Mac's sound goes. The game (Wine's CoreAudio driver) keeps the output device it starts with, so
    headphones picked afterwards stay silent, and so does an output that is muted. Tab-separated, since device
    names have spaces: "ok <output>", "muted <output>", "virtual <output>" (a virtual device such as a meeting
    app's, with no speaker behind it) or "headset <headphones> <output>" (Bluetooth headphones connected but not
    the output). Plain "ok" when macOS can't tell: never keeps anyone from playing."""
    devices = output_devices()
    output = next((name for name, is_default, _ in devices if is_default), None)
    if not output:
        return "ok"
    if output_muted():
        return f"muted\t{output}"
    transport = next(t for name, is_default, t in devices if is_default)
    if "virtual" in transport:
        return f"virtual\t{output}"
    headset = next((name for name, is_default, t in devices if not is_default and "bluetooth" in t), None)
    if headset:
        return f"headset\t{headset}\t{output}"
    return f"ok\t{output}"


CRASHES = [
    ("stopped responding, so the game had to close",
     "The graphics card stopped responding, so the game closed. This happens now and then on heavy modded maps. "
     "Press Play to start again; if it keeps happening, lower Settings > Render resolution in the game."),
    ("device lost",
     "The graphics card stopped responding, so the game closed. Press Play to start again."),
    (" panicked at ",
    "Project Gravemind hit an error and closed. Press Play to start again. If it keeps happening, use "
     "Tools > Send a report."),
]


def crash_check():
    try:
        text = (LOGS / "client-wine.log").read_text(errors="replace")[-200000:]
    except OSError:
        return "ok"
    for marker, message in CRASHES:
        if marker in text:
            return "crash: " + message
    return "ok"


STARTUP_DETAIL = {
    "starting": "The game is starting.",
    "building": "Building the Forge asset library. The first start takes a while.",
    "ready": "The game is up.",
    "stalled": "Startup stopped progressing: the Forge asset library has written nothing since the game started. "
               "That build needs more free memory than this Mac has available; quit other apps and try again.",
    "stopped": "The game isn't running.",
}


def prefix_user():
    """The Wine prefix's user folder: Reclaimer's own AppData lives under it."""
    users = BASE / "prefix-wine" / "drive_c" / "users"
    try:
        found = [u for u in users.iterdir() if u.name != "Public"]
    except OSError:
        return None
    return found[0] if found else None


def forge_cache():
    """Reclaimer's Forge asset library: %LOCALAPPDATA%\\ProjectReclaimer\\forge-maps."""
    user = prefix_user()
    return None if user is None else user / "AppData" / "Local" / "ProjectReclaimer" / "forge-maps"


def cache_progress(folder):
    """The build's only visible progress: what it has written, and when it last wrote."""
    info, newest = {"bytes": 0, "files": 0, "newest_age_s": None}, None
    if folder is None or not folder.is_dir():
        return info, newest
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:  # (the game may be replacing it as we look)
            continue
        info["bytes"] += stat.st_size
        info["files"] += 1
        newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
    if newest is not None:
        info["newest_age_s"] = round(time.time() - newest)
    return info, newest


def game_elapsed_seconds():
    """How long the game client has been running, or None if it isn't."""
    pids = game_process.pids(BASE)
    if not pids:
        return None
    stamp = subprocess.run(["ps", "-o", "etime=", "-p", pids[0]], capture_output=True, text=True).stdout.strip()
    if not stamp:
        return None
    days = 0
    if "-" in stamp:
        day, stamp = stamp.split("-", 1)
        days = int(day)
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3:]
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


STARTUP_MARKERS = {"build_started": b"Forge library: building it while the game starts",
                   "menu_loaded": b'"map_loaded":true',
                   "overlay_finished": b"Menu loading screen finished"}


def startup_markers():
    """Which startup markers the game has logged, anywhere in its log.

    The log is scanned from the start, not from a tail window: the Forge build marker is logged near the top (byte
    ~1,300 in the run that found this), so a 400 KB tail loses it once diagnostics fill the file — which made a
    stalled build decay back to "starting". Chunks overlap by the longest marker so a match split across a boundary
    still counts, and the scan stops once every marker is found.
    """
    found = {name: False for name in STARTUP_MARKERS}
    overlap = b""
    longest = max(len(needle) for needle in STARTUP_MARKERS.values())
    try:
        with open(LOGS / "client-wine.log", "rb") as log:
            while True:
                chunk = log.read(1 << 18)
                if not chunk:
                    break
                window = overlap + chunk
                for name, needle in STARTUP_MARKERS.items():
                    if not found[name] and needle in window:
                        found[name] = True
                if all(found.values()):
                    break
                overlap = window[-(longest - 1):]
    except OSError:
        pass
    return found


def startup_state():
    """Whether startup is progressing, or a named stall, instead of waiting on a window that looks busy.

    Reclaimer builds its Forge asset library while the game starts and shows "BUILDING ASSET LIBRARY" until it is
    done. On a Mac too small to hold the build, it can write nothing for half an hour while the window spins, so the
    process being alive says nothing. This reads the cache's progress and the log's markers instead.
    """
    markers = startup_markers()
    elapsed = game_elapsed_seconds()
    cache, newest_write = cache_progress(forge_cache())
    started_at = None if elapsed is None else time.time() - elapsed
    wrote_this_run = newest_write is not None and started_at is not None and newest_write >= started_at
    if elapsed is None:
        state = "stopped"
    elif markers["overlay_finished"]:
        state = "ready"
    elif markers["build_started"] and elapsed >= FORGE_STALL_SECONDS and not wrote_this_run:
        state = "stalled"
    elif markers["build_started"]:
        state = "building"
    else:
        state = "starting"
    return json.dumps({"state": state, "detail": STARTUP_DETAIL[state], "elapsed_s": elapsed,
                       "stall_after_s": FORGE_STALL_SECONDS, "wrote_this_run": wrote_this_run,
                       "forge_cache": cache, "markers": markers})



def force_quit():
    # the game first, by force: a frozen game often comes with a stuck wineserver, which must not stop this.
    # Only this install's game: another checkout's game (or another test run's) is not ours to kill.
    for pid in game_process.pids(BASE):
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError):  # (it exited between the match and the kill)
            pass
    env = dict(os.environ, WINEPREFIX=str(BASE / "prefix-wine"))
    wineserver = BASE / "wine" / "Wine Staging.app" / "Contents" / "Resources" / "wine" / "bin" / "wineserver"
    if wineserver.exists():
        try:
            subprocess.run([str(wineserver), "-k"], env=env, capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            pass
    subprocess.run(["pkill", "-9", "-f", str(BASE / "wine") + "/"], capture_output=True)
    for _ in range(10):
        if not game_running():
            return "ok"
        time.sleep(0.5)
    return "error: The game didn't stop. Restart your Mac (Apple menu > Restart) to close it."


def folder_size(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def mod_title(folder):
    try:
        info = json.loads((folder / "ModInfo.json").read_text(encoding="utf-8-sig"))
        return info.get("Title", {}).get("Neutral", "").strip() or folder.name
    except (OSError, ValueError, AttributeError):
        return folder.name


def mods():
    items = []
    if WORKSHOP.exists():
        for d in WORKSHOP.iterdir():
            if d.is_dir() and d.name.isdigit():
                items.append({"id": d.name, "title": mod_title(d), "bytes": folder_size(d)})
    items.sort(key=lambda m: -m["bytes"])
    return json.dumps({"free_bytes": shutil.disk_usage(BASE).free, "mods": items})


def remove_mod(wid):
    if not (wid.isascii() and wid.isdigit()):
        return "error: That isn't a Workshop item."
    if game_running():
        return "error: Quit the game first."
    folder = WORKSHOP / wid
    if not folder.is_dir():
        return "error: That mod isn't downloaded."
    shutil.rmtree(folder)
    (LOGS / "mods" / f"{wid}.json").unlink(missing_ok=True)
    try:
        helper().write_manifest()  # the game checks Steam's manifest to know what's installed
    except Exception as e:  # (offline: the manifest is rewritten on the next game)
        sys.stderr.write(f"could not update the Workshop manifest: {e}\n")
    return "ok"


def startup_evidence():
    """What startup is doing, for the report: (readable lines, the startup state's own answer).

    Startup-state is the one source of truth for this (the window reads the same answer), so the report carries it
    rather than working anything out again. A probe that cannot answer must not stop the report being made, so the
    lines say so and there is no data to attach.
    """
    try:
        state = json.loads(startup_state())
        cache, elapsed = state["forge_cache"], state["elapsed_s"]
        when = f"{elapsed} s elapsed" if elapsed is not None else "not running"
        writes = "cache written this run" if state["wrote_this_run"] else "no cache writes this run"
        files = "file" if cache["files"] == 1 else "files"
        last = (f"last write {cache['newest_age_s']} s ago" if cache["newest_age_s"] is not None
                else "never written")
        return [f"Startup: {state['state']}, {when} (stall threshold {state['stall_after_s']} s, {writes})",
                "Startup detail: " + state["detail"],
                f"Forge cache: {cache['bytes']} bytes in {cache['files']} {files}, {last}"], state
    except Exception:  # (an unreadable startup state is not a reason to withhold the logs)
        return ["Startup: unknown (the startup check failed)"], None


def report():
    account = ""
    try:
        account = (BASE / "steam-account").read_text().strip()
    except OSError:
        pass

    def scrub(text):
        if account:
            text = text.replace(account, "<steam account>")
        # (and names logged before a Forget Steam, and the Mac's user name in paths)
        text = re.sub(r"(-username|Signed in as|login with -username) \S+", r"\1 <steam account>", text)
        return text.replace(str(HOME), "~")
    summary = [f"Project Gravemind Mac Port report, {time.strftime('%Y-%m-%d %H:%M')}"]

    for label, cmd in [("macOS", ["sw_vers", "-productVersion"]), ("Mac", ["sysctl", "-n", "machdep.cpu.brand_string"]),
                       ("Memory", ["sysctl", "-n", "hw.memsize"])]:
        value = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        summary.append(f"{label}: " + (f"{int(value) / 2**30:.0f} GB" if label == "Memory" and value.isdigit() else value))
    try:
        summary.append("Mac port version: " + (BASE / "version").read_text().strip())
    except OSError:
        summary.append("Mac port version: 1.0 or older")
    try:
        version = (GAME / "gravemind" / ".release-version").read_text().strip()
    except OSError:
        version = "not installed"
    summary.append("Project Gravemind: " + version)
    summary.append("Halo 2 installed: " + ("yes" if game_installed("halo2") else "no"))
    summary.append(f"Free disk space: {shutil.disk_usage(BASE).free / 1e9:.0f} GB")
    DESKTOP.mkdir(parents=True, exist_ok=True)
    path = DESKTOP / f"Project Gravemind report {time.strftime('%Y-%m-%d %H.%M')}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("summary.txt", scrub("\n".join(summary) + "\n"))
        for log in sorted(LOGS.glob("*.log")):
            z.writestr(f"logs/{log.name}", scrub(log.read_text(errors="replace")[-2_000_000:]))
    return f"ok {path}"


def reset_graphics():
    if game_running():  # (the game writes its settings when it quits)
        return "error: Quit the game first."
    p = subprocess.run([sys.executable, "-I", str(GAME / "presets.py"), "wine"], capture_output=True, text=True,
                       env=dict(os.environ, RECLAIMER_HOME=str(BASE)))
    return "ok" if p.returncode == 0 else "error: The graphics settings couldn't be changed."


def forget_steam():
    (BASE / "steam-account").unlink(missing_ok=True)
    return "ok"


# id: (title, folder in MCC_DIR, its depots). Each game's depots write only into its folder; MCC's shared files
# (BASE_DEPOT: MCC/, Data/, Engine/) come with either and stay when one is removed.
GAMES = {"halo2": ("Halo 2", "halo2", ["976735", "976736", "976737"])}
BASE_DEPOT = "976731"
GAME_GB = {"halo2": 78}  # campaign, both multiplayer depots, and MCC shared files


def game_installed(gid):
    root = MCC_DIR / GAMES[gid][1]
    return game_campaign_installed(gid) and game_multiplayer_installed(gid)


def game_campaign_installed(gid):
    root = MCC_DIR / GAMES[gid][1]
    return any((root / "preload" / "paks").glob("*.pck"))


def game_multiplayer_installed(gid):
    root = MCC_DIR / GAMES[gid][1]
    return (root / "h2_maps_win64_dx11" / "ascension.map").is_file()


def download_games(ids):
    if game_running():
        return "error: Quit the game first."
    depots = [BASE_DEPOT] + [d for gid in ids for d in GAMES[gid][2]]
    return helper().game_download(str(MCC_DIR), depots)


def repair():
    """Check Halo 2 campaign and multiplayer files against Steam."""
    return download_games(["halo2"])


def repair_game(gid):
    if gid not in GAMES:
        return "error: That isn't a game Project Gravemind plays."
    if game_running():
        return "error: Quit the game first."
    if not game_installed(gid):
        return f"error: {GAMES[gid][0]} isn't installed. Add it first."
    return download_games([gid])


def add_games(ids):
    if not ids or any(gid not in GAMES for gid in ids):
        return "error: That isn't a game Project Gravemind plays."
    need = 4  # spare space for DepotDownloader and temporary files
    for gid in ids:
        if game_installed(gid):
            continue
        if gid == "halo2" and game_campaign_installed(gid):
            need += 30  # both multiplayer depots
        elif gid == "halo2" and game_multiplayer_installed(gid):
            need += 32  # campaign depot
        else:
            need += GAME_GB[gid]
    free = shutil.disk_usage(BASE).free / 1e9
    if free < need:
        return (f"error: That needs about {need} GB free, and your Mac has {free:.0f} GB. Free up some space "
                "(Tools > Mods and disk space can remove downloaded mods), then try again.")
    result = download_games(ids)
    return result


def games():
    items = []
    for gid, (title, folder, _) in GAMES.items():
        path = MCC_DIR / folder
        items.append({"id": gid, "title": title, "installed": game_installed(gid), "path": str(path),
                      "bytes": folder_size(path) if path.is_dir() else 0})  # (what Remove frees)
    return json.dumps({"free_bytes": shutil.disk_usage(BASE).free, "games": items,
                       "mcc_bytes": folder_size(MCC_DIR) if MCC_DIR.is_dir() else 0})


def remove_game(gid):
    if gid not in GAMES:
        return "error: That isn't a game Project Gravemind plays."
    title, folder, depots = GAMES[gid]
    if game_running():
        return "error: Quit the game first."
    if not (MCC_DIR / folder).is_dir():
        return f"error: {title} isn't installed."
    try:
        shutil.rmtree(MCC_DIR / folder)
    except OSError as e:
        return f"error: {title}'s folder couldn't be removed ({e.strerror or e}). Is it on another disk or in use?"
    # DepotDownloader's record of the depots, so adding the game again downloads it all
    for depot in depots:
        for f in (MCC_DIR / ".DepotDownloader").glob(depot + "_*.manifest*"):
            f.unlink(missing_ok=True)
    return "ok"


def controller_mappings_file():
    """Bundled database, plus any user calibrations from the launcher (as run.sh does)."""
    bundled = GAME / "gamecontrollerdb.txt"
    user = BASE / "controller-mappings.txt"
    db = bundled
    if user.is_file():
        db = BASE / "controller-mappings-active.txt"
        parts = []
        if bundled.is_file():
            parts.append(bundled.read_text("utf-8", errors="ignore"))
        parts.append(user.read_text("utf-8", errors="ignore"))
        try:
            db.write_text("\n".join(parts), "utf-8")
        except OSError:
            pass
    return str(db) if db.is_file() and db.stat().st_size > 0 else None


def game_env():
    """Wine settings as run.sh uses them, for asking the game something without opening it."""
    env = dict(os.environ, WINEPREFIX=str(BASE / "prefix-wine"), WINEDEBUG="-all", MVK_CONFIG_LOG_LEVEL="0",
               WINEDLLOVERRIDES="opengl32=n,b;xaudio2_9=d;d3d11,d3d10core=n,b")
    # ~/.zshenv may inject an arm64 DYLD shim (libnomallocstacklogging) globally; Wine runs as an x86_64/Rosetta binary.
    env.pop("DYLD_INSERT_LIBRARIES", None)
    db = controller_mappings_file()
    if db:
        env["SDL_GAMECONTROLLERCONFIG_FILE"] = db
    return env


def uninstall():
    if not (BASE / "game").is_dir() or not (BASE / "prefix-wine").is_dir():
        return f"error: {BASE} doesn't look like a Project Gravemind install, so nothing was removed."
    stopped = force_quit()
    if stopped != "ok":
        return stopped  # (nothing deleted while the game still runs)
    subprocess.run(["pkill", "-f", str(GAME / "workshop_helper.py")], capture_output=True)  # (only this install's)
    shutil.rmtree(APP, ignore_errors=True)
    shutil.rmtree(BASE, ignore_errors=True)
    return "ok"


COMMANDS = {"controller-check": controller_check,
            "audio-check": audio_check, "crash-check": crash_check, "startup-state": startup_state,
            "force-quit": force_quit, "mods": mods,
            "report": report, "reset-graphics": reset_graphics, "forget-steam": forget_steam, "repair": repair,
            "games": games, "uninstall": uninstall}


def main(argv):
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    if len(argv) == 3 and argv[1] == "remove-mod":
        result = remove_mod(argv[2])
    elif len(argv) == 3 and argv[1] == "remove-game":
        result = remove_game(argv[2])
    elif len(argv) == 3 and argv[1] == "repair-game":
        result = repair_game(argv[2])
    elif len(argv) >= 3 and argv[1] == "add-game":
        result = add_games(argv[2:])
    elif len(argv) == 2 and argv[1] in COMMANDS:
        result = COMMANDS[argv[1]]()
    else:
        print(__doc__)
        return 2
    say(result)
    return 1 if result.startswith("error: ") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Update the Mac port and Project Gravemind before launch (run by the launcher window).

  updater.py run    the Mac port (when GitHub has a newer VERSION, re-run its installer in update mode), then the game
    updater.py game   only the game: install the latest Project Gravemind release ZIP if needed
    updater.py versions        JSON: recent Gravemind releases
    updater.py use <version>   install and select a specific Gravemind release; "use newest" returns to latest

Each ZIP is checked against the SHA-256 digest published in the GitHub release API before its files are installed.

Prints one line per event for the launcher: "status: <text>", "progress: <0-100>", "relaunch" (the launcher itself
was replaced), and last "done: up to date|updated", "offline: <reason>" or "error: <reason>". Offline or failed
updates never stop the game from starting.
"""
import fcntl
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(os.environ.get("RECLAIMER_HOME", Path.home() / "Games" / "ProjectGravemind"))
REPO = "drewdrew21b/project-gravemind-mac-port"
REPO_RAW = os.environ.get("RECLAIMER_REPO_RAW", f"https://raw.githubusercontent.com/{REPO}/main")
GAME = BASE / "game"
GAME_PACKAGE = GAME / "gravemind"
VERSIONS = GAME / "versions"          # older Gravemind builds chosen for compatibility
CHOSEN = GAME / "chosen-version"
RELEASE_API = os.environ.get("GRAVEMIND_RELEASE_API", "https://api.github.com/repos/BriRoz1/"
                             "h2gravemind-releases/releases/latest")
RELEASES_API = os.environ.get("GRAVEMIND_RELEASES_API", "https://api.github.com/repos/BriRoz1/"
                              "h2gravemind-releases/releases?per_page=100")
GAME_PROCESS = os.environ.get("GRAVEMIND_GAME_PROCESS",
                              re.escape(str(GAME)) + r"/(?:gravemind|versions/v[0-9.]+)/h2gravemind\.exe")
UA = {"User-Agent": "project-gravemind-mac-port"}


class Offline(Exception):
    pass


def say(line):
    try:
        print(line, flush=True)
    except BrokenPipeError:
        # the window closed: finish the update anyway (stopping halfway left a half-updated install), quietly
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)


def fetch(url, timeout=20):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise Offline(str(getattr(e, "reason", e))) from e


def fetch_json(url):
    try:
        return json.loads(fetch(url).decode())
    except (UnicodeDecodeError, ValueError) as e:
        raise RuntimeError("the Project Gravemind release data couldn't be read") from e


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "0")[:3]) or (0,)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def game_running():
    return subprocess.run(["pgrep", "-a", "-f", GAME_PROCESS], capture_output=True).returncode == 0  # (-a: see helper)


# ---------------------------------------------------------------------------------------------------------------
def pinned_repo_raw():
    """REPO_RAW at main's current commit, so VERSION, install.sh, the launcher and the scripts all come from one
    commit (GitHub caches raw files on main for minutes, so files fetched separately could mix two versions)."""
    if "RECLAIMER_REPO_RAW" in os.environ:
        return REPO_RAW
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/main",
                                     headers={**UA, "Accept": "application/vnd.github.sha"})
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = r.read().decode().strip()
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return f"https://raw.githubusercontent.com/{REPO}/{sha}"
    except (urllib.error.URLError, OSError):
        pass  # (e.g. API rate limit) main is nearly always fine
    return REPO_RAW


def installed_port_version():
    try:
        return (BASE / "version").read_text().strip()
    except OSError:
        return "0"  # installed before versions were recorded


def update_port():
    """Returns "current", "updated" (installer ran; the launcher was rebuilt) or raises."""
    raw = pinned_repo_raw()
    latest = fetch(f"{raw}/VERSION").decode().strip()
    if version_tuple(latest) <= version_tuple(installed_port_version()):
        return "current"
    say(f"status: Updating the Mac port to {latest}…")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "install.sh"
        script.write_bytes(fetch(f"{raw}/install.sh"))
        env = dict(os.environ, RECLAIMER_HOME=str(BASE), RECLAIMER_REPO_RAW=raw, RECLAIMER_UPDATE="1",
                   RECLAIMER_EXPECT_VERSION=latest,
                   RECLAIMER_UPDATE_LOCKED="1")  # install.sh runs `updater.py game` under this run's lock
        # Stop the installer and its downloads with this updater when the launcher watchdog fires.
        p = subprocess.Popen(["/bin/bash", str(script)], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)

        def stop_installer(signum, _frame):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            sys.exit(128 + signum)

        signal.signal(signal.SIGTERM, stop_installer)
        tail = []
        steps = 0
        for line in p.stdout:
            line = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip()
            tail = (tail + [line])[-30:]
            if line.startswith("==> "):
                steps += 1
                say(f"progress: {min(95, steps * 7)}")  # the installer has ~13 steps
        p.wait()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if p.returncode != 0:
        err = next((l for l in reversed(tail) if l.strip()), "installer failed")
        raise RuntimeError(re.sub(r"^Error: ", "", err.strip()))
    if installed_port_version() != latest:  # relaunching would only start the same update again
        raise RuntimeError(f"the update to {latest} didn't install; it will be tried again next time")
    return "updated"


def release_version(release):
    tag = str(release.get("tag_name", ""))
    match = re.fullmatch(r"v(\d+(?:\.\d+){1,3})", tag)
    if not match:
        raise RuntimeError("that Project Gravemind release has an invalid version")
    return match.group(1)


def release_asset(release):
    """Return the version and checksum-verified ZIP asset from a Gravemind release."""
    version = release_version(release)
    for asset in release.get("assets", []):
        if asset.get("name") != "h2gravemind.zip":
            continue
        digest = str(asset.get("digest", ""))
        match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest)
        url = asset.get("browser_download_url")
        if match and url:
            return version, url, match.group(1).lower()
    raise RuntimeError(f"Project Gravemind {version} has no verifiable h2gravemind.zip")


def latest_release():
    return release_asset(fetch_json(RELEASE_API))


def download_verified(url, target, expected):
    """Download to target with progress lines, keeping it only if its SHA-256 matches."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)
        except (urllib.error.URLError, OSError) as e:
            raise Offline(str(getattr(e, "reason", e))) from e
        with r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, shown = 0, -1
            for block in iter(lambda: r.read(1 << 18), b""):
                f.write(block)
                done += len(block)
                pct = done * 100 // total if total else 0
                if pct != shown:
                    say(f"progress: {pct}")
                    shown = pct
        if sha256(part) != expected:
            raise RuntimeError("the Project Gravemind download didn't match its checksum; kept the current version")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def install_release(version, url, expected, target):
    """Verify and atomically install the release ZIP, rejecting paths outside its package folder."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        work = Path(tmp)
        archive = work / "h2gravemind.zip"
        download_verified(url, archive, expected)
        extracted = work / "package"
        extracted.mkdir()
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                path = Path(item.filename)
                if path.is_absolute() or len(path.parts) != 1 or ".." in path.parts:
                    raise RuntimeError("the Project Gravemind ZIP contains an unsafe path")
                if item.is_dir():
                    continue
                with package.open(item) as source, (extracted / path.name).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        if not (extracted / "h2gravemind.exe").is_file():
            raise RuntimeError("the Project Gravemind ZIP is missing h2gravemind.exe")
        (extracted / ".release-version").write_text(version + "\n")
        (extracted / ".release-sha256").write_text(expected + "\n")
        (extracted / ".release-exe-sha256").write_text(sha256(extracted / "h2gravemind.exe") + "\n")
        backup = work / "previous"
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(extracted, target)
        except OSError:
            if backup.exists():
                os.replace(backup, target)
            raise


def update_game():
    """Returns "current", "updated", "running" (left alone while the game runs) or "chosen" (the player picked an
    older release), or raises."""
    if CHOSEN.exists():
        return "chosen"
    version, url, expected = latest_release()
    marker = GAME_PACKAGE / ".release-sha256"
    exe = GAME_PACKAGE / "h2gravemind.exe"
    exe_marker = GAME_PACKAGE / ".release-exe-sha256"
    if (exe.is_file() and marker.is_file() and marker.read_text().strip() == expected and exe_marker.is_file()
            and exe_marker.read_text().strip() == sha256(exe)):
        return "current"
    if game_running():
        return "running"
    say(f"status: Updating Project Gravemind to {version}…")
    install_release(version, url, expected, GAME_PACKAGE)
    return "updated"


def versions():
    """Recent verified releases for the window's version list (prereleases left out)."""
    listing = fetch_json(RELEASES_API)
    chosen = CHOSEN.read_text().strip() if CHOSEN.exists() else None
    items = []
    for r in listing:
        if r.get("prerelease") or r.get("draft"):
            continue
        try:
            version, _, _ = release_asset(r)
        except RuntimeError:
            continue
        items.append({"version": version, "date": str(r.get("published_at", ""))[:10],
                      "downloaded": (VERSIONS / f"v{version}" / "h2gravemind.exe").is_file()
                      or (version == (GAME_PACKAGE / ".release-version").read_text().strip()
                          if (GAME_PACKAGE / ".release-version").is_file() else False)})
    return json.dumps({"chosen": chosen, "versions": items})


def use(version):
    """Choose the release to play: an older one (downloaded once, then kept), or "newest"."""
    if version == "newest":
        CHOSEN.unlink(missing_ok=True)
        return update_game()
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        raise RuntimeError(f"{version} isn't a Project Gravemind version")
    release = next((r for r in fetch_json(RELEASES_API) if r.get("tag_name") == f"v{version}"), None)
    if release is None:
        raise RuntimeError(f"Project Gravemind {version} wasn't found")
    release_version_value, url, expected = release_asset(release)
    target = VERSIONS / f"v{release_version_value}"
    marker = target / ".release-sha256"
    exe = target / "h2gravemind.exe"
    exe_marker = target / ".release-exe-sha256"
    valid = (exe.is_file() and marker.is_file() and marker.read_text().strip() == expected and exe_marker.is_file()
             and exe_marker.read_text().strip() == sha256(exe))
    if not valid:
        say(f"status: Downloading Project Gravemind {version}…")
        install_release(version, url, expected, target)
    CHOSEN.write_text(version + "\n")
    return "chosen"


def main(argv):
    if len(argv) == 2 and argv[1] == "versions":
        try:
            say(versions())
            return 0
        except Offline as e:
            say(f"offline: {e}")
            return 1
        except Exception as e:
            say(f"error: {e}")
            return 1
    if len(argv) == 3 and argv[1] == "use":
        try:
            result = use(argv[2])
        except Offline as e:
            say(f"error: Couldn't download it ({e}). Check your internet connection and try again.")
            return 1
        except Exception as e:
            say(f"error: {e}")
            return 1
        if result == "chosen":
            say(f"done: using {argv[2]}")
        else:
            say("done: updated" if result == "updated" else "done: up to date")
        return 0
    if len(argv) != 2 or argv[1] not in ("run", "game"):
        print(__doc__)
        return 2
    BASE.mkdir(parents=True, exist_ok=True)
    lock = open(BASE / ".update.lock", "w")  # one update at a time (e.g. the app opened twice)
    if not os.environ.get("RECLAIMER_UPDATE_LOCKED"):  # (set when run by install.sh inside a port update)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            say("status: Waiting for another update to finish…")
            fcntl.flock(lock, fcntl.LOCK_EX)
    say("status: Checking for updates…")
    results, errors, offline = {}, [], None
    if argv[1] == "run":
        # an older version is for this session only (Tools, or the window's "switch and rejoin"): opening the app
        # again goes back to the newest, so nobody stays stuck on an old one
        CHOSEN.unlink(missing_ok=True)
    steps = [update_game] if argv[1] == "game" else [update_port, update_game]
    for step in steps:
        if step is update_game and results.get("update_port") == "updated":
            break  # the new install.sh just updated the game with the new updater.py; this one's code is the old one
        try:
            results[step.__name__] = step()
            sys.stderr.write(f"updater: {step.__name__}: {results[step.__name__]}\n")
        except Offline as e:
            sys.stderr.write(f"updater: {step.__name__}: can't connect: {e}\n")
            offline = offline or str(e)
        except Exception as e:  # report and carry on: a failed update never blocks the game
            sys.stderr.write(f"updater: {step.__name__}: {e}\n")
            errors.append(str(e))
    if results.get("update_port") == "updated":
        say("relaunch")
    results = list(results.values())
    if errors:
        say(f"error: {errors[0]}")
        return 1
    if offline and "updated" not in results:  # (checks that could connect found nothing to do)
        say(f"offline: {offline}")
        return 0
    if "chosen" in results:
        say(f"done: using {CHOSEN.read_text().strip()}")
    elif "updated" in results:
        say("done: updated")
    elif "running" in results:
        say("done: skipped while the game is running")
    else:
        say("done: up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

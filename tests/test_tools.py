"""Tests for scripts/tools.py (the launcher's Tools menu and auto-fixes), in throwaway homes.

Tests and install paths are isolated in throwaway folders. Run: /usr/bin/python3 -I -m unittest discover -s tests
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "scripts" / "tools.py"
WORKSHOP = Path("prefix-wine/drive_c/Program Files (x86)/Steam/steamapps/workshop")


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "Games" / "ProjectGravemind"
        for d in ("game", "logs", "tools", WORKSHOP / "content" / "976730"):
            (self.home / d).mkdir(parents=True)
        # the helper scripts sit next to tools.py in an install's game folder
        for f in ("workshop_helper.py", "presets.py", "fit.py"):
            shutil.copy(REPO / "scripts" / f, self.home / "game" / f)
        shutil.copy(TOOLS, self.home / "game" / "tools.py")
        self.apps = self.tmp / "Applications"
        (self.apps / "Project Gravemind.app" / "Contents").mkdir(parents=True)
        self.desktop = self.tmp / "Desktop"
        self.desktop.mkdir()
        self.env = dict(os.environ, RECLAIMER_HOME=str(self.home),
                        RECLAIMER_APPS_DIR=str(self.apps), RECLAIMER_DESKTOP=str(self.desktop),
                        GRAVEMIND_GAME_PROCESS=r"h2gravemind\.exe")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_tool(self, *args, **env):
        p = subprocess.run([sys.executable, "-I", str(self.home / "game" / "tools.py"), *args],
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.splitlines()

    def load(self):
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location("tools", self.home / "game" / "tools.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def add_mod(self, wid, title, size):
        d = self.home / WORKSHOP / "content" / "976730" / wid
        d.mkdir()
        (d / "ModInfo.json").write_text(json.dumps({"Title": {"Neutral": title}}))
        (d / "data.bin").write_bytes(b"x" * size)
        (d / ".reclaimer-complete").write_text('{"timeupdated": 1, "manifest": "1"}')
        return d

    # ---- controllers -------------------------------------------------------------------------------------------
    def test_controller_check_reports_a_stuck_macos_controller_service(self):
        # macOS's gamecontrollerd can get stuck in the kernel (state U): every app that looks for controllers then
        # hangs, so Wine never lists the controller and the game ignores it although Bluetooth says connected
        t = self.load()
        with mock.patch.object(t, "gamecontrollerd_state", return_value="Us"), mock.patch.object(t.time, "sleep"):
            self.assertEqual(t.controller_check(), "stuck")

    def test_controller_check_ignores_a_moment_of_waiting(self):
        t = self.load()
        with mock.patch.object(t, "gamecontrollerd_state", side_effect=["Us", "Ss", "Us"]), \
                mock.patch.object(t.time, "sleep"):
            self.assertEqual(t.controller_check(), "ok")
        for state in ("Ss", None):  # healthy, or not running at all (macOS starts it when needed)
            with mock.patch.object(t, "gamecontrollerd_state", return_value=state), mock.patch.object(t.time, "sleep"):
                self.assertEqual(t.controller_check(), "ok")

    def test_gamecontrollerd_state_reads_the_process_list(self):
        t = self.load()
        ps = "Ss   /usr/sbin/bluetoothd\nUs   /usr/libexec/gamecontrollerd\n"
        with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout=ps)):
            self.assertEqual(t.gamecontrollerd_state(), "Us")
        with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout="Ss   /usr/sbin/bluetoothd\n")):
            self.assertIsNone(t.gamecontrollerd_state())

    def test_controller_check_command(self):
        rc, out = self.run_tool("controller-check")
        self.assertEqual(rc, 0)
        self.assertIn(out[-1], ("ok", "stuck"))

    # ---- sound -------------------------------------------------------------------------------------------------
    SPEAKERS = ("MacBook Pro Speakers", True, "coreaudio_device_type_builtin")
    AIRPODS = ("Chris AirPods Pro", False, "coreaudio_device_type_bluetooth")
    TEAMS = ("Microsoft Teams Audio", False, "coreaudio_device_type_virtual")

    def audio(self, devices, muted=False):
        t = self.load()
        with mock.patch.object(t, "output_devices", return_value=devices), \
                mock.patch.object(t, "output_muted", return_value=muted):
            return t.audio_check()

    def test_audio_check_says_where_the_sound_goes(self):
        # the game keeps the output it starts with, so the window shows it before Play
        self.assertEqual(self.audio([self.SPEAKERS, self.TEAMS]), "ok\tMacBook Pro Speakers")
        airpods_chosen = [self.SPEAKERS[:1] + (False,) + self.SPEAKERS[2:], self.AIRPODS[:1] + (True,) + self.AIRPODS[2:]]
        self.assertEqual(self.audio(airpods_chosen), "ok\tChris AirPods Pro")

    def test_audio_check_warns_about_a_muted_output(self):
        self.assertEqual(self.audio([self.SPEAKERS, self.AIRPODS], muted=True), "muted\tMacBook Pro Speakers")

    def test_audio_check_warns_about_headphones_that_are_not_the_output(self):
        # AirPods connected (e.g. from the iPhone) while the Mac still plays through its speakers: the game would
        # start on the speakers and stay there even after the AirPods are put in
        self.assertEqual(self.audio([self.SPEAKERS, self.AIRPODS, self.TEAMS]),
                         "headset\tChris AirPods Pro\tMacBook Pro Speakers")

    def test_audio_check_warns_about_a_virtual_output(self):
        teams_chosen = [self.SPEAKERS[:1] + (False,) + self.SPEAKERS[2:], self.TEAMS[:1] + (True,) + self.TEAMS[2:]]
        self.assertEqual(self.audio(teams_chosen), "virtual\tMicrosoft Teams Audio")

    def test_audio_check_is_quiet_when_macos_cannot_tell(self):
        self.assertEqual(self.audio([]), "ok")
        self.assertEqual(self.audio([self.SPEAKERS], muted=None), "ok\tMacBook Pro Speakers")

    def test_output_devices_reads_system_profiler(self):
        t = self.load()
        profile = json.dumps({"SPAudioDataType": [{"_items": [
            {"_name": "MacBook Pro Microphone", "coreaudio_device_input": 1,
             "coreaudio_device_transport": "coreaudio_device_type_builtin"},
            {"_name": "MacBook Pro Speakers", "coreaudio_default_audio_output_device": "spaudio_yes",
             "coreaudio_device_output": 2, "coreaudio_device_transport": "coreaudio_device_type_builtin"},
            {"_name": "Chris AirPods Pro", "coreaudio_device_input": 1, "coreaudio_device_output": 2,
             "coreaudio_device_transport": "coreaudio_device_type_bluetooth"}]}]})
        with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout=profile)):
            self.assertEqual(t.output_devices(), [self.SPEAKERS, self.AIRPODS])
        renamed = json.dumps({"SPAudioDataType": [{"_items": [
            {"_name": "Studio\tMonitors\n", "coreaudio_default_audio_output_device": "spaudio_yes",
             "coreaudio_device_output": 2, "coreaudio_device_transport": "coreaudio_device_type_usb"}]}]})
        with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout=renamed)):
            self.assertEqual(t.output_devices(), [("Studio Monitors", True, "coreaudio_device_type_usb")])  # (one field)
        with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout="not json")):
            self.assertEqual(t.output_devices(), [])
        with mock.patch.object(t.subprocess, "run", side_effect=OSError):
            self.assertEqual(t.output_devices(), [])

    def test_output_muted_reads_the_volume_settings(self):
        t = self.load()
        for answer, expected in (("true\n", True), ("false\n", False), ("", None)):
            with mock.patch.object(t.subprocess, "run", return_value=mock.Mock(stdout=answer)):
                self.assertEqual(t.output_muted(), expected)

    def test_audio_check_command(self):
        rc, out = self.run_tool("audio-check")
        self.assertEqual(rc, 0)
        self.assertIn(out[-1].split("\t")[0], ("ok", "muted", "virtual", "headset"))

    # ---- crash check -------------------------------------------------------------------------------------------
    def test_crash_check(self):
        log = self.home / "logs" / "client-wine.log"
        log.write_text("Menu loading screen finished.\n")
        self.assertEqual(self.run_tool("crash-check")[1][-1], "ok")
        log.write_text("...\nYour graphics card stopped responding, so the game had to close.\n")
        self.assertTrue(self.run_tool("crash-check")[1][-1].startswith("crash: The graphics card stopped"))
        log.write_text("thread 'main' panicked at src/thing.rs:1:2:\nboom\n")
        self.assertTrue(self.run_tool("crash-check")[1][-1].startswith("crash: Project Gravemind hit an error"))

    # ---- startup state (the watchdog) --------------------------------------------------------------------------

    def start_fake_game(self):
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                 "h2gravemind.exe"])

        def stop():  # (kill and reap, so no ResourceWarning about a still-running child)
            game.kill()
            game.wait()

        self.addCleanup(stop)
        time.sleep(0.2)  # (pgrep needs the process to have registered)
        return game

    def write_log(self, text):
        (self.home / "logs" / "client-wine.log").write_text(text)

    def write_cache(self, payload=b""):
        """A Forge cache file under the prefix user, the way the build writes them."""
        folder = (self.home / "prefix-wine/drive_c/users/player/AppData/Local/ProjectReclaimer"
                  "/forge-maps/virtual/x")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "130_epilogue.map").write_bytes(payload)
        return folder

    def startup(self, **env):
        return json.loads(self.run_tool("startup-state", **env)[1][-1])

    def test_startup_state_is_stopped_when_the_game_is_not_running(self):
        self.write_log("Forge library: building it while the game starts.\n")
        self.assertEqual(self.startup()["state"], "stopped")

    def test_startup_state_with_nothing_installed_reports_stopped(self):
        # no prefix, no log, no cache (a first run, or an install that stopped partway): the probe must answer, not
        # crash, and must not invent a state
        shutil.rmtree(self.home / "prefix-wine")
        shutil.rmtree(self.home / "logs")
        state = self.startup()
        self.assertEqual(state["state"], "stopped")
        self.assertIsNone(state["elapsed_s"])
        self.assertEqual(state["forge_cache"], {"bytes": 0, "files": 0, "newest_age_s": None})

    def test_startup_state_is_ready_once_the_loading_screen_finishes(self):
        self.start_fake_game()
        self.write_log("Menu loading screen finished.\n")
        self.assertEqual(self.startup()["state"], "ready")

    def test_startup_state_is_building_while_the_library_is_written(self):
        self.start_fake_game()
        self.write_log("Forge library: building it while the game starts.\n")
        self.assertEqual(self.startup()["state"], "building")

    def test_the_build_marker_survives_a_log_that_grows_past_a_tail_window(self):
        # the marker is logged near the top; diagnostics later fill the file, which is what a real stall looks like.
        # Reading only the last 400 KB lost it, so a stalled build decayed back to "starting".
        self.write_cache()  # (left over from an earlier run: nothing written this run)
        time.sleep(1.2)
        self.start_fake_game()
        self.write_log("Forge library: building it while the game starts.\n" + ("diagnostic line\n" * 40000))
        state = self.startup(RECLAIMER_STALL_SECONDS="0")
        self.assertTrue(state["markers"]["build_started"])
        self.assertEqual(state["state"], "stalled")

    def test_startup_state_names_a_stall_when_nothing_is_written_this_run(self):
        self.write_cache()  # (a leftover from an earlier run: nothing written since this start)
        time.sleep(1.2)  # (ps reports elapsed in whole seconds, so make the ordering unambiguous)
        self.start_fake_game()
        self.write_log("Forge library: building it while the game starts.\n")
        state = self.startup(RECLAIMER_STALL_SECONDS="0")
        self.assertEqual(state["state"], "stalled")
        self.assertFalse(state["wrote_this_run"])
        self.assertIn("Forge asset library", state["detail"])

    def test_startup_state_is_not_stalled_before_the_threshold(self):
        self.write_cache()  # (an older build's cache: nothing written this run)
        time.sleep(1.2)  # (as above: the cache has to be clearly before this start)
        self.start_fake_game()
        self.write_log("Forge library: building it while the game starts.\n")
        state = self.startup(RECLAIMER_STALL_SECONDS="3600")
        self.assertEqual(state["state"], "building")  # (too soon to call it a stall)

    def test_startup_state_is_not_stalled_while_the_cache_is_writing(self):
        self.start_fake_game()
        time.sleep(1.2)  # (as above: the write has to be clearly after the start)
        self.write_log("Forge library: building it while the game starts.\n")
        self.write_cache(payload=b"x" * 10)  # (written after this start)
        state = self.startup(RECLAIMER_STALL_SECONDS="0")
        self.assertTrue(state["wrote_this_run"])
        self.assertEqual(state["state"], "building")

    # ---- mods --------------------------------------------------------------------------------------------------
    def test_mods_lists_titles_sizes_and_free_space(self):
        self.add_mod("111", "Warlock", 3000)
        self.add_mod("222", "Lockout", 1000)
        rc, out = self.run_tool("mods")
        data = json.loads(out[-1])
        self.assertGreater(data["free_bytes"], 0)
        self.assertEqual([(m["id"], m["title"]) for m in data["mods"]], [("111", "Warlock"), ("222", "Lockout")])
        self.assertGreaterEqual(data["mods"][0]["bytes"], 3000)

    def test_remove_mod_deletes_it_and_its_status(self):
        d = self.add_mod("111", "Warlock", 10)
        (self.home / "logs" / "mods").mkdir()
        (self.home / "logs" / "mods" / "111.json").write_text("{}")
        t = self.load()
        with mock.patch.object(t.helper(), "write_manifest") as manifest:
            self.assertEqual(t.remove_mod("111"), "ok")
        self.assertFalse(d.exists())
        self.assertFalse((self.home / "logs" / "mods" / "111.json").exists())
        self.assertTrue(manifest.called)  # the game must stop counting it as installed

    def test_remove_mod_refuses_while_the_game_runs_and_rejects_odd_ids(self):
        self.add_mod("111", "Warlock", 10)
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                 "h2gravemind.exe"])
        try:
            self.assertEqual(self.run_tool("remove-mod", "111")[1][-1], "error: Quit the game first.")
        finally:
            game.kill()
        self.assertTrue(self.run_tool("remove-mod", "../../etc")[1][-1].startswith("error: "))

    # ---- report ------------------------------------------------------------------------------------------------
    def test_report_zips_logs_without_the_steam_account(self):
        (self.home / "steam-account").write_text("SecretName\n")
        (self.home / "version").write_text("1.2.0\n")
        (self.home / "logs" / "launcher.log").write_text("launcher steam: done(\"Signed in as SecretName\")\n")
        (self.home / "logs" / "client-wine.log").write_text("Menu loading screen finished.\n")
        rc, out = self.run_tool("report")
        self.assertTrue(out[-1].startswith("ok "), out)
        path = Path(out[-1][3:])
        self.assertEqual(path.parent, self.desktop)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            text = "".join(z.read(n).decode("utf-8", "replace") for n in names)
        self.assertIn("client-wine.log", " ".join(names))
        self.assertIn("summary.txt", names)
        self.assertIn("1.2.0", text)
        self.assertNotIn("SecretName", text)
        self.assertNotIn("steam-account", " ".join(names))

    def test_report_identifies_gravemind_and_halo2_install_state(self):
        self.fake_mcc(halo2=True)
        (self.home / "game" / "gravemind").mkdir(parents=True)
        (self.home / "game" / "gravemind" / ".release-version").write_text("0.18.374\n")
        rc, out = self.run_tool("report")
        self.assertEqual(rc, 0, out)
        with zipfile.ZipFile(Path(out[-1][3:])) as z:
            summary = z.read("summary.txt").decode()
        self.assertIn("Project Gravemind: 0.18.374", summary)
        self.assertIn("Halo 2 installed: yes", summary)
        self.assertNotIn("Forge cache", summary)
    def test_report_leaves_out_the_mac_user_name_and_logged_steam_names(self):
        (self.home / "logs" / "launcher.log").write_text(
            f"started (home {Path.home()}/Games/ProjectGravemind)\nDepotDownloader -username OldName -remember-password\n")
        rc, out = self.run_tool("report")
        with zipfile.ZipFile(Path(out[-1][3:])) as z:
            text = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
        self.assertNotIn(str(Path.home()), text)
        self.assertIn("~/Games/ProjectGravemind", text)
        self.assertNotIn("OldName", text)  # (after Forget Steam the account file is gone, but logs still name it)

    # ---- Steam account and Halo 2 game files ------------------------------------------------------------------
    def test_forget_steam(self):
        (self.home / "steam-account").write_text("RealName_1\n")
        self.assertEqual(self.run_tool("forget-steam")[1][-1], "ok")
        self.assertFalse((self.home / "steam-account").exists())

    def fake_mcc(self, halo2=True, multiplayer=True):
        mcc = self.home / "prefix-wine/drive_c/Program Files (x86)/Steam/steamapps/common/Halo The Master Chief Collection"
        (mcc / "MCC").mkdir(parents=True)
        (mcc / "MCC" / "shared.pak").write_bytes(b"x" * 500)
        (mcc / ".DepotDownloader").mkdir()
        (mcc / ".DepotDownloader" / "976731_1.manifest").write_bytes(b"m")
        if halo2:
            paks = mcc / "halo2" / "preload" / "paks"
            paks.mkdir(parents=True)
            (paks / "campaign.pck").write_bytes(b"x" * 3000)
            (mcc / ".DepotDownloader" / "976735_2.manifest").write_bytes(b"m")
        if multiplayer:
            maps = mcc / "halo2" / "h2_maps_win64_dx11"
            maps.mkdir(parents=True)
            (maps / "ascension.map").write_bytes(b"m" * 1000)
            for depot in ("976736_4", "976737_5"):
                (mcc / ".DepotDownloader" / f"{depot}.manifest").write_bytes(b"m")
        return mcc

    def test_games_lists_halo2_campaign_files(self):
        mcc = self.fake_mcc()
        data = json.loads(self.run_tool("games")[1][-1])
        halo2, = data["games"]
        self.assertEqual((halo2["id"], halo2["installed"], halo2["bytes"], halo2["path"]),
                         ("halo2", True, 4000, str(mcc / "halo2")))

    def test_campaign_without_multiplayer_is_not_installed(self):
        self.fake_mcc(multiplayer=False)
        halo2, = json.loads(self.run_tool("games")[1][-1])["games"]
        self.assertFalse(halo2["installed"])

    def test_games_reports_missing_halo2(self):
        self.fake_mcc(halo2=False)
        halo2, = json.loads(self.run_tool("games")[1][-1])["games"]
        self.assertEqual((halo2["installed"], halo2["bytes"]), (False, 1000))

    def test_add_game_downloads_shared_and_halo2_depots(self):
        self.fake_mcc(halo2=False)
        tools = self.load()
        with mock.patch.object(tools.helper(), "game_download", return_value="ok") as download, \
            mock.patch.object(tools.shutil, "disk_usage", return_value=mock.Mock(free=200 * 10**9)), \
            mock.patch.object(tools, "game_running", return_value=False):
            self.assertEqual(tools.add_games(["halo2"]), "ok")
            download.assert_called_with(str(tools.MCC_DIR), ["976731", "976735", "976736", "976737"])

    def test_campaign_only_install_needs_only_multiplayer_space(self):
        self.fake_mcc(multiplayer=False)
        tools = self.load()
        with mock.patch.object(tools.helper(), "game_download", return_value="ok") as download, \
            mock.patch.object(tools.shutil, "disk_usage", return_value=mock.Mock(free=35 * 10**9)), \
            mock.patch.object(tools, "game_running", return_value=False):
            self.assertEqual(tools.add_games(["halo2"]), "ok")
        download.assert_called_once_with(str(tools.MCC_DIR), ["976731", "976735", "976736", "976737"])

    def test_repair_checks_halo2_files(self):
        self.fake_mcc()
        tools = self.load()
        with mock.patch.object(tools.helper(), "game_download", return_value="ok") as download:
            self.assertEqual(tools.repair_game("halo2"), "ok")
            download.assert_called_once_with(str(tools.MCC_DIR), ["976731", "976735", "976736", "976737"])
            self.assertEqual(tools.repair(), "ok")

    def test_add_game_requires_space_for_campaign_multiplayer_and_mcc(self):
        self.fake_mcc(halo2=False)
        tools = self.load()
        with mock.patch.object(tools.helper(), "game_download") as download, \
                mock.patch.object(tools.shutil, "disk_usage", return_value=mock.Mock(free=5 * 10**9)):
            result = tools.add_games(["halo2"])
        self.assertIn("GB", result)
        download.assert_not_called()

    def test_remove_game_only_deletes_halo2_files(self):
        mcc = self.fake_mcc()
        self.assertEqual(self.run_tool("remove-game", "halo2")[1][-1], "ok")
        self.assertFalse((mcc / "halo2").exists())
        self.assertTrue((mcc / "MCC" / "shared.pak").exists())
        self.assertEqual(sorted(f.name for f in (mcc / ".DepotDownloader").iterdir()), ["976731_1.manifest"])

    def test_remove_game_refuses_invalid_ids(self):
        self.fake_mcc(halo2=False, multiplayer=False)
        self.assertIn("isn't installed", self.run_tool("remove-game", "halo2")[1][-1])
        self.assertIn("Project Gravemind plays", self.run_tool("remove-game", "../halo2")[1][-1])

    # ---- force quit / uninstall --------------------------------------------------------------------------------
    def test_force_quit_stops_the_game(self):
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                 "h2gravemind.exe"])
        try:
            rc, out = self.run_tool("force-quit")
            self.assertEqual(out[-1], "ok")
            game.wait(timeout=10)
        finally:
            if game.poll() is None:
                game.kill()
        self.assertIsNotNone(game.poll())

    def test_force_quit_works_when_wineserver_hangs(self):
        # a frozen game often means a stuck wineserver: Force Quit must still stop the game, and not hang
        ws = self.home / "wine/Wine Staging.app/Contents/Resources/wine/bin/wineserver"
        ws.parent.mkdir(parents=True)
        ws.write_text("#!/bin/sh\nsleep 120\n")
        ws.chmod(0o755)
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                 "h2gravemind.exe"])
        try:
            rc, out = self.run_tool("force-quit")
            self.assertEqual(out[-1], "ok", out)
            game.wait(timeout=5)
        finally:
            if game.poll() is None:
                game.kill()
            subprocess.run(["pkill", "-f", str(ws)])

    def test_uninstall_leaves_the_system_network_task_untouched(self):
        daemon = self.tmp / "local.projectreclaimer.loopback.plist"
        daemon.write_text("<plist/>")
        rc, out = self.run_tool("uninstall")
        self.assertEqual(out[-1], "ok")
        self.assertTrue(daemon.exists())
        self.assertFalse([l for l in out if l.startswith("dry-run admin: ")])

    def test_uninstall_removes_only_the_gravemind_app_and_install(self):
        (self.apps / "Project Reclaimer.app").mkdir()
        rc, out = self.run_tool("uninstall")
        self.assertEqual(out[-1], "ok", out)
        self.assertFalse(self.home.exists())
        self.assertTrue((self.apps / "Project Reclaimer.app").exists())
        self.assertFalse((self.apps / "Project Gravemind.app").exists())

    def test_uninstall_removes_its_local_halo2_files(self):
        mcc = self.fake_mcc()
        self.assertEqual(self.run_tool("uninstall")[1][-1], "ok")
        self.assertFalse((mcc / "halo2").exists())
        self.assertFalse(self.home.exists())

    def test_uninstall_only_stops_this_installs_helpers(self):
        # e.g. another install's QR sign-in: the reviewer's test run once killed a live sign-in this way
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                  "/elsewhere/game/workshop_helper.py", "login-qr"])
        try:
            self.run_tool("uninstall")
            self.assertIsNone(other.poll(), "uninstall stopped another install's helper")
        finally:
            other.kill()

    def test_uninstall_removes_the_app_the_player_opened(self):
        moved = self.tmp / "Elsewhere" / "Project Gravemind.app"
        moved.mkdir(parents=True)
        self.run_tool("uninstall", RECLAIMER_APP_PATH=str(moved))
        self.assertFalse(moved.exists())

    def test_uninstall_refuses_a_home_that_isnt_an_install(self):
        rc, out = self.run_tool("uninstall", RECLAIMER_HOME=str(self.tmp))
        self.assertTrue(out[-1].startswith("error: "))
        self.assertTrue(self.tmp.exists())

    def test_game_env_sets_sdl_controller_config_file_when_mappings_exist(self):
        spec = importlib.util.spec_from_file_location("tools", str(self.home / "game" / "tools.py"))
        tools = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"RECLAIMER_HOME": str(self.home)}):
            spec.loader.exec_module(tools)
            (tools.GAME / "gamecontrollerdb.txt").write_text("guid,bundled,platform:Mac OS X,\n")
            (tools.BASE / "controller-mappings.txt").write_text("guid,user,platform:Mac OS X,\n")
            env = tools.game_env()
            self.assertEqual(env.get("SDL_GAMECONTROLLERCONFIG_FILE"), str(tools.BASE / "controller-mappings-active.txt"))
            self.assertIn("guid,user", (tools.BASE / "controller-mappings-active.txt").read_text())

    def test_game_env_leaves_sdl_controller_config_file_unset_when_no_mappings(self):
        spec = importlib.util.spec_from_file_location("tools", str(self.home / "game" / "tools.py"))
        tools = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"RECLAIMER_HOME": str(self.home)}):
            spec.loader.exec_module(tools)
            (tools.GAME / "gamecontrollerdb.txt").unlink(missing_ok=True)
            (tools.BASE / "controller-mappings.txt").unlink(missing_ok=True)
            (tools.BASE / "controller-mappings-active.txt").unlink(missing_ok=True)
            env = tools.game_env()
            self.assertNotIn("SDL_GAMECONTROLLERCONFIG_FILE", env)


if __name__ == "__main__":
    unittest.main()

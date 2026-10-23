"""scripts/run.sh starts Project Gravemind with Wine and forwards explicit arguments."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class RunTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        package = self.home / "game" / "gravemind"
        package.mkdir(parents=True)
        shutil.copy(REPO / "scripts" / "run.sh", self.home / "game" / "run.sh")
        (package / "h2gravemind.exe").write_bytes(b"MZ")
        wine = self.home / "wine" / "Wine Staging.app" / "Contents" / "Resources" / "wine" / "bin" / "wine"
        wine.parent.mkdir(parents=True)
        wine.write_text('#!/bin/sh\nprintf "cwd=%s exe=%s args=%s cfgfile=%s wine=%s dxvk=%s dxvkpath=%s\\n" "$(pwd)" "$1" "$*" "$SDL_GAMECONTROLLERCONFIG_FILE" "$WINEDEBUG" "$DXVK_LOG_LEVEL" "$DXVK_LOG_PATH"\n')
        wine.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.home)

    def run_game(self, *args, extra_env=None):
        env = dict(os.environ, RECLAIMER_HOME=str(self.home))
        if extra_env:
            env.update(extra_env)
        process = subprocess.run(["/bin/zsh", str(self.home / "game" / "run.sh"), *args],
                                 capture_output=True, text=True, env=env, timeout=30)
        return process.stdout.strip()

    def test_launches_gravemind_without_reclaimer_arguments(self):
        out = self.run_game()
        self.assertIn(f"cwd={self.home}/game/gravemind", out)
        self.assertIn(f"exe={self.home}/game/gravemind/h2gravemind.exe", out)
        self.assertNotIn("--mcc-path", out)
        self.assertNotIn("game-client", out)
        self.assertIn("wine=-all,err+d3d,err+vulkan,err+mmdevapi,err+coreaudio", out)
        self.assertIn("dxvk=warn", out)
        self.assertIn("dxvkpath=", out)

    def test_debug_mode_enables_wine_exception_network_and_dxvk_logs(self):
        out = self.run_game(extra_env={"GRAVEMIND_DEBUG": "1"})
        self.assertIn("wine=+timestamp,+pid,+tid,+file,err+all,+seh,+winsock,+winhttp,+wininet", out)
        self.assertIn("dxvk=info", out)
        self.assertIn(f"dxvkpath={self.home}/logs", out)

    def test_unset_home_uses_the_projectgravemind_default(self):
        base = self.home / "Games" / "ProjectGravemind"
        package = base / "game" / "gravemind"
        package.mkdir(parents=True)
        (package / "h2gravemind.exe").write_bytes(b"MZ")
        run = base / "game" / "run.sh"
        shutil.copy(REPO / "scripts" / "run.sh", run)
        wine = base / "wine" / "Wine Staging.app" / "Contents" / "Resources" / "wine" / "bin" / "wine"
        wine.parent.mkdir(parents=True)
        wine.write_text('#!/bin/sh\nprintf "cwd=%s exe=%s\\n" "$(pwd)" "$1"\n')
        wine.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home))
        env.pop("RECLAIMER_HOME", None)
        process = subprocess.run(["/bin/zsh", str(run)], capture_output=True, text=True, env=env, timeout=30)
        self.assertIn(f"cwd={package}", process.stdout)
        self.assertIn(f"exe={package}/h2gravemind.exe", process.stdout)

    def test_explicit_arguments_are_forwarded(self):
        out = self.run_game("--server", "--map-id", "44")
        self.assertIn("h2gravemind.exe --server --map-id 44", out)

    def test_selected_older_release_starts_from_its_package_folder(self):
        older = self.home / "game" / "versions" / "v0.18.373"
        older.mkdir(parents=True)
        (older / "h2gravemind.exe").write_bytes(b"MZ older")
        (self.home / "game" / "chosen-version").write_text("0.18.373\n")
        out = self.run_game()
        self.assertIn(f"cwd={older}", out)
        self.assertIn(f"exe={older}/h2gravemind.exe", out)

    def test_bundled_controller_mapping_is_used_directly(self):
        bundled = "03000000c82d00002f20000000000000,8BitDo,a:b0,b:b1,platform:Mac OS X,\n"
        (self.home / "game" / "gamecontrollerdb.txt").write_text(bundled)
        out = self.run_game()
        self.assertIn(f"cfgfile={self.home}/game/gamecontrollerdb.txt", out)
        self.assertFalse((self.home / "controller-mappings-active.txt").exists())

    def test_controller_mappings_combine_database_and_user_calibrations(self):
        bundled = "03000000c82d00002f20000000000000,8BitDo,a:b0,b:b1,platform:Mac OS X,\n"
        user = "030000007e0500000920000000000000,Switch Pro,a:b1,b:b0,platform:Mac OS X,\n"
        (self.home / "game" / "gamecontrollerdb.txt").write_text(bundled)
        (self.home / "controller-mappings.txt").write_text(user)
        out = self.run_game()
        active = self.home / "controller-mappings-active.txt"
        self.assertIn(f"cfgfile={active}", out)
        self.assertEqual(active.read_text().splitlines(), [bundled.strip(), user.strip()])

    def test_no_controller_mappings_leaves_config_unset(self):
        out = self.run_game()
        self.assertIn("cfgfile=", out)
        self.assertNotIn("cfgfile=/", out)
        self.assertFalse((self.home / "controller-mappings-active.txt").exists())

    def test_missing_executable_fails_clearly(self):
        (self.home / "game" / "gravemind" / "h2gravemind.exe").unlink()
        process = subprocess.run(["/bin/zsh", str(self.home / "game" / "run.sh")],
                                 env=dict(os.environ, RECLAIMER_HOME=str(self.home)), capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("Project Gravemind is not installed", process.stderr)

    def test_debug_wrapper_preserves_the_normal_log(self):
        base = self.home / "Games" / "ProjectGravemind"
        game = base / "game"
        logs = base / "logs"
        game.mkdir(parents=True)
        logs.mkdir(parents=True)
        (logs / "client-wine.log").write_text("previous crash\n")
        shutil.copy(REPO / "scripts" / "launch.sh", game / "launch.sh")
        runner = game / "run.sh"
        runner.write_text("#!/bin/sh\necho debug launch\n")
        runner.chmod(0o755)
        process = subprocess.run(["/bin/zsh", str(game / "launch.sh")],
                                 env=dict(os.environ, RECLAIMER_HOME=str(base), GRAVEMIND_DEBUG="1"),
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual((logs / "client-wine.log").read_text(), "previous crash\n")
        self.assertEqual((logs / "client-wine-debug.log").read_text(), "debug launch\n")


class LaunchTest(unittest.TestCase):
    """scripts/launch.sh (the Play button): the helper and the game start from the game folder, wherever it's run from,
    since that's how the install-scoped process rule (game_process.py) tells this install's processes apart."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        game = self.home / "game"
        game.mkdir()
        shutil.copy(REPO / "scripts" / "launch.sh", game / "launch.sh")
        (game / "workshop_helper.py").write_text(
            f"import os\nopen({str(self.home / 'helper-cwd')!r}, 'w').write(os.getcwd())\n")
        (game / "run.sh").write_text(f'#!/bin/sh\npwd > "{self.home / "game-cwd"}"\n')
        (game / "run.sh").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.home)

    def test_helper_and_game_start_from_the_game_folder(self):
        subprocess.run(["/bin/zsh", str(self.home / "game" / "launch.sh")], cwd="/", timeout=30,
                       env=dict(os.environ, RECLAIMER_HOME=str(self.home)))
        for _ in range(50):
            if (self.home / "helper-cwd").exists():
                break
            time.sleep(0.1)
        self.assertEqual((self.home / "game-cwd").read_text().strip(), str(self.home / "game"))
        self.assertEqual((self.home / "helper-cwd").read_text(), str(self.home / "game"))


if __name__ == "__main__":
    unittest.main()

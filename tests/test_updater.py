"""Updater tests against local stand-ins for the Gravemind GitHub API and release assets."""
import hashlib
import io
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

REPO = Path(__file__).resolve().parent.parent
UPDATER = REPO / "scripts" / "updater.py"


def package_bytes(executable=b"MZ Gravemind", extra=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as package:
        package.writestr("h2gravemind.exe", executable)
        package.writestr("LEGAL.md", "legal")
        for name, content in (extra or {}).items():
            package.writestr(name, content)
    return data.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.assets = self.tmp / "assets"
        self.assets.mkdir()
        self.latest_api = self.tmp / "latest.json"
        self.releases_api = self.tmp / "releases.json"
        self.latest_zip = package_bytes()
        self.old_zip = package_bytes(b"MZ older Gravemind")
        (self.assets / "latest.zip").write_bytes(self.latest_zip)
        (self.assets / "old.zip").write_bytes(self.old_zip)
        latest = self.release("v0.18.374", self.assets / "latest.zip", self.latest_zip)
        older = self.release("v0.18.373", self.assets / "old.zip", self.old_zip)
        self.latest_api.write_text(json.dumps(latest))
        self.releases_api.write_text(json.dumps([latest, older, {
            "tag_name": "v0.19.0-rc1", "prerelease": True, "draft": False,
            "published_at": "2026-10-11T00:00:00Z", "assets": []
        }]))
        self.env = dict(os.environ, RECLAIMER_HOME=str(self.home),
                        GRAVEMIND_RELEASE_API=self.latest_api.as_uri(),
                        GRAVEMIND_RELEASES_API=self.releases_api.as_uri(),
                        GRAVEMIND_GAME_PROCESS=r"not-a-real-game-process")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    @staticmethod
    def release(tag, archive, content):
        return {"tag_name": tag, "published_at": "2026-10-10T13:20:51Z",
                "prerelease": False, "draft": False,
                "assets": [{"name": "h2gravemind_beta.zip", "digest": f"sha256:{sha(content)}",
                            "browser_download_url": archive.as_uri()}]}

    def run_updater(self, *args, **env):
        process = subprocess.run([sys.executable, "-I", str(UPDATER), *args],
                                 env=dict(self.env, **env), capture_output=True, text=True, timeout=60)
        return process.returncode, process.stdout.splitlines()

    @property
    def package_dir(self):
        return self.home / "game" / "gravemind"

    def test_latest_release_installs_verified_zip(self):
        rc, output = self.run_updater("game")
        self.assertEqual(rc, 0, output)
        self.assertIn("status: Updating Project Gravemind to 0.18.374…", output)
        self.assertIn("gravemind-status: Checking for updates…", output)
        self.assertIn("gravemind-done: 0.18.374: updated", output)
        self.assertTrue(any(line.startswith("gravemind-progress: ") for line in output), output)
        self.assertEqual(output[-1], "done: Project Gravemind 0.18.374: updated")
        self.assertEqual((self.package_dir / "h2gravemind.exe").read_bytes(), b"MZ Gravemind")
        self.assertEqual((self.package_dir / ".release-version").read_text().strip(), "0.18.374")
        self.assertEqual((self.package_dir / ".release-sha256").read_text().strip(), sha(self.latest_zip))
        self.assertEqual((self.package_dir / "LEGAL.md").read_text(), "legal")

    def test_verified_release_is_not_downloaded_twice(self):
        self.run_updater("game")
        exe = self.package_dir / "h2gravemind.exe"
        rc, output = self.run_updater("game")
        self.assertEqual(rc, 0, output)
        self.assertEqual(output[-1], "done: Project Gravemind 0.18.374: up to date")
        self.assertEqual(exe.read_bytes(), b"MZ Gravemind")

    def test_run_reports_mac_port_and_gravemind_versions(self):
        self.home.mkdir()
        (self.home / "version").write_text("0.8.3\n")
        raw = self.tmp / "port-release"
        raw.mkdir()
        (raw / "VERSION").write_text("0.8.3\n")

        rc, output = self.run_updater("run", RECLAIMER_REPO_RAW=raw.as_uri())

        self.assertEqual(rc, 0, output)
        self.assertEqual(output[-1], "done: Mac port 0.8.3: up to date; Project Gravemind 0.18.374: updated")

    def test_game_only_check_reports_installed_port_version(self):
        self.home.mkdir()
        (self.home / "version").write_text("0.8.3\n")

        rc, output = self.run_updater("game")

        self.assertEqual(rc, 0, output)
        self.assertEqual(output[-1], "done: Mac port 0.8.3: installed; Project Gravemind 0.18.374: updated")

    def test_modified_executable_is_repaired_from_verified_release(self):
        self.run_updater("game")
        (self.package_dir / "h2gravemind.exe").write_bytes(b"damaged")
        rc, output = self.run_updater("game")
        self.assertEqual(rc, 0, output)
        self.assertEqual(output[-1], "done: Project Gravemind 0.18.374: updated")
        self.assertEqual((self.package_dir / "h2gravemind.exe").read_bytes(), b"MZ Gravemind")

    def test_checksum_mismatch_keeps_installed_release(self):
        self.run_updater("game")
        old_exe = self.package_dir / "h2gravemind.exe"
        old_exe.write_bytes(b"known-good")
        tampered = b"tampered archive"
        (self.assets / "latest.zip").write_bytes(tampered)
        expected_archive = package_bytes(b"MZ Gravemind 0.18.375")
        latest = self.release("v0.18.375", self.assets / "latest.zip", expected_archive)
        self.latest_api.write_text(json.dumps(latest))
        rc, output = self.run_updater("game")
        self.assertNotEqual(rc, 0)
        self.assertTrue(output[-1].startswith("error: "), output)
        self.assertEqual(old_exe.read_bytes(), b"known-good")
        self.assertEqual(list(self.home.rglob("*.part")), [])

    def test_archive_path_traversal_is_rejected_without_replacing_install(self):
        self.run_updater("game")
        old_exe = self.package_dir / "h2gravemind.exe"
        old_exe.write_bytes(b"known-good")
        unsafe_zip = package_bytes(extra={"../outside.txt": "bad"})
        (self.assets / "latest.zip").write_bytes(unsafe_zip)
        latest = self.release("v0.18.375", self.assets / "latest.zip", unsafe_zip)
        self.latest_api.write_text(json.dumps(latest))
        releases = json.loads(self.releases_api.read_text())
        releases.insert(0, latest)
        self.releases_api.write_text(json.dumps(releases))
        rc, output = self.run_updater("game")
        self.assertNotEqual(rc, 0)
        self.assertIn("unsafe path", output[-1])
        self.assertEqual(old_exe.read_bytes(), b"known-good")
        self.assertFalse((self.tmp / "outside.txt").exists())

    def test_versions_and_older_release_install(self):
        rc, output = self.run_updater("versions")
        listing = json.loads(output[-1])
        self.assertEqual([item["version"] for item in listing["versions"]], ["0.18.374", "0.18.373"])
        self.assertIsNone(listing["chosen"])
        rc, output = self.run_updater("use", "0.18.373")
        self.assertEqual(rc, 0, output)
        self.assertIn("gravemind-done: 0.18.373: selected for this session", output)
        self.assertEqual(output[-1], "done: using 0.18.373")
        self.assertEqual((self.home / "game" / "versions" / "v0.18.373" / "h2gravemind.exe").read_bytes(),
                         b"MZ older Gravemind")
        self.assertEqual((self.home / "game" / "chosen-version").read_text().strip(), "0.18.373")

    def test_stopping_a_port_update_stops_the_installer_and_its_downloads(self):
        raw = self.tmp / "port-release"
        raw.mkdir()
        (raw / "VERSION").write_text("1.2.0\n")
        (raw / "install.sh").write_text(
            "#!/bin/bash\n"
            "sleep 300 &\n"
            "echo \"$$ $!\" > \"$RECLAIMER_HOME/hung-pids\"\n"
            "wait\n"
        )
        process = subprocess.Popen([sys.executable, "-I", str(UPDATER), "run"],
                                   env=dict(self.env, RECLAIMER_REPO_RAW=raw.as_uri()),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pids_file = self.home / "hung-pids"
        pids = []
        try:
            deadline = time.monotonic() + 10
            while not pids_file.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(pids_file.exists(), "fake installer did not start")
            pids = [int(pid) for pid in pids_file.read_text().split()]
            process.terminate()
            process.wait(timeout=10)
            for pid in pids:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    self.fail(f"child process {pid} kept running after the update was stopped")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass

    def test_invalid_version_is_rejected(self):
        rc, output = self.run_updater("use", "../../x")
        self.assertNotEqual(rc, 0)
        self.assertTrue(output[-1].startswith("error: "))


if __name__ == "__main__":
    unittest.main()

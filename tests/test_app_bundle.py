"""The installed Gravemind app bundle (scripts/make_app.sh).

make_app.sh builds into a throwaway apps folder (RECLAIMER_APPS_DIR), never ~/Applications.
Run: /usr/bin/python3 -I -m unittest discover -s tests
"""
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/"
              "lsregister")


class AppBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "home" / "tools").mkdir(parents=True)
        shutil.copy(REPO / "launcher" / "ProjectReclaimer", self.tmp / "home" / "tools" / "ProjectReclaimer")
        shutil.copy(REPO / "launcher" / "Resources" / "AppIcon.icns", self.tmp / "home" / "tools" / "AppIcon.icns")
        self.app = self.tmp / "apps" / "Project Gravemind.app"

    def tearDown(self):
        subprocess.run([LSREGISTER, "-u", str(self.app)], capture_output=True)
        shutil.rmtree(self.tmp)

    def test_app_asks_for_the_microphone_for_voice_chat(self):
        # without a usage description macOS never prompts: the game (started by the app) silently gets silence
        env = dict(os.environ, RECLAIMER_HOME=str(self.tmp / "home"), RECLAIMER_APPS_DIR=str(self.tmp / "apps"))
        env.pop("RECLAIMER_APP_PATH", None)
        subprocess.run(["/bin/bash", str(REPO / "scripts" / "make_app.sh"), "Project Gravemind", "9.9.9"], env=env,
                       check=True, capture_output=True, timeout=60)
        info = plistlib.loads((self.app / "Contents" / "Info.plist").read_bytes())
        self.assertIn("voice chat", info.get("NSMicrophoneUsageDescription", ""))
        self.assertEqual((self.app / "Contents" / "Resources" / "AppIcon.icns").read_bytes(),
                 (self.tmp / "home" / "tools" / "AppIcon.icns").read_bytes())
        self.assertEqual(subprocess.run(["codesign", "-v", str(self.app)], capture_output=True).returncode, 0)


class LegacyNetworkFilesTest(unittest.TestCase):
    def test_gravemind_install_does_not_ship_reclaimer_loopback_files(self):
        self.assertFalse((REPO / "scripts" / "reclaimer-loopback.sh").exists())
        self.assertFalse((REPO / "scripts" / "local.projectreclaimer.loopback.plist").exists())
        for path in (REPO / "install.sh", REPO / "scripts" / "tools.py"):
            self.assertNotIn("reclaimer-loopback.sh", path.read_text())


if __name__ == "__main__":
    unittest.main()

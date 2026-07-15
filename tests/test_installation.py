import os
import json
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


class InstallationTests(unittest.TestCase):
    def test_user_install_creates_valid_launcher_and_uninstalls_cleanly(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            data_home = home / "share"
            bin_home = home / "bin"
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(data_home),
                "XDG_BIN_HOME": str(bin_home),
            }

            install_result = subprocess.run(
                [project / "scripts/install.sh"],
                cwd=project,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("pixel-pet --help", install_result.stdout)

            command = bin_home / "pixel-pet"
            desktop = data_home / "applications/com.abhi.pixelpet.desktop"
            icon = data_home / "icons/hicolor/64x64/apps/com.abhi.pixelpet.png"
            self.assertTrue(command.stat().st_mode & stat.S_IXUSR)
            self.assertTrue(desktop.is_file())
            self.assertTrue(icon.is_file())
            self.assertTrue((data_home / "pixel-pet/pet.py").is_file())
            self.assertTrue(
                (data_home / "pixel-pet/companion_presentation.py").is_file()
            )
            self.assertTrue((data_home / "pixel-pet/behavior_input.py").is_file())
            self.assertTrue((data_home / "pixel-pet/behavior_scheduler.py").is_file())
            self.assertTrue((data_home / "pixel-pet/niri_monitor.py").is_file())
            self.assertTrue((data_home / "pixel-pet/live_settings.py").is_file())
            subprocess.run(["desktop-file-validate", desktop], check=True)

            version = subprocess.run(
                [command, "version"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(version.stdout.strip(), "Pixel Pet 0.2.0")

            help_result = subprocess.run(
                [command, "--help"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertIn("pixel-pet update", help_result.stdout)
            self.assertIn("pixel-pet uninstall --purge", help_result.stdout)

            subprocess.run(
                [command, "uninstall"],
                cwd=project,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(command.exists())
            self.assertFalse(desktop.exists())
            self.assertFalse(icon.exists())
            self.assertFalse((data_home / "pixel-pet").exists())

    def test_purge_uninstall_removes_settings(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(home / "share"),
                "XDG_BIN_HOME": str(home / "bin"),
                "XDG_CONFIG_HOME": str(home / "config"),
            }
            subprocess.run(
                [project / "scripts/install.sh"],
                cwd=project,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            settings = home / "config/pixel-pet/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text("{}", encoding="utf-8")

            subprocess.run(
                [home / "bin/pixel-pet", "uninstall", "--purge"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(settings.parent.exists())

    def test_update_check_reports_newer_stable_release(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            release = home / "release.json"
            release.write_text(
                json.dumps({
                    "tag_name": "v0.3.0",
                    "tarball_url": "https://example.invalid/pixel-pet.tar.gz",
                }),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(home / "share"),
                "XDG_BIN_HOME": str(home / "bin"),
                "PIXEL_PET_RELEASE_API": release.as_uri(),
            }
            subprocess.run(
                [project / "scripts/install.sh"],
                cwd=project,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            result = subprocess.run(
                [home / "bin/pixel-pet", "update", "--check"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("0.3.0 is available", result.stdout)

    def test_update_installs_newer_stable_release(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            release_root = home / "pixel-pet-0.2.0"
            shutil.copytree(
                project,
                release_root,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"),
            )
            (release_root / "VERSION").write_text("0.2.0\n", encoding="utf-8")
            archive = home / "pixel-pet-0.2.0.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(release_root, arcname=release_root.name)
            release = home / "release.json"
            release.write_text(
                json.dumps({
                    "tag_name": "v0.2.0",
                    "tarball_url": archive.as_uri(),
                }),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_DATA_HOME": str(home / "share"),
                "XDG_BIN_HOME": str(home / "bin"),
                "PIXEL_PET_RELEASE_API": release.as_uri(),
            }
            subprocess.run(
                [project / "scripts/install.sh"],
                cwd=project,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            subprocess.run(
                [home / "bin/pixel-pet", "update"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            version = subprocess.run(
                [home / "bin/pixel-pet", "version"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(version.stdout.strip(), "Pixel Pet 0.2.0")


if __name__ == "__main__":
    unittest.main()

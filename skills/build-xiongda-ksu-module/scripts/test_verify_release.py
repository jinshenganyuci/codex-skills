#!/usr/bin/env python3
"""Regression tests for verify_release.py using inert temporary fixtures."""

from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


VERIFIER = Path(__file__).with_name("verify_release.py")


def fixture_files() -> dict[str, bytes]:
    return {
        "module.prop": (
            "id=A.fixture-module\n"
            "name=Fixture\n"
            "version=1.0\n"
            "versionCode=1\n"
            "author=test\n"
            "description=inert verifier fixture\n"
        ).encode(),
        "action.sh": (
            '#!/system/bin/sh\nMODDIR=${0%/*}\n'
            'exec /system/bin/sh "$MODDIR/bin/run-payload" run\n'
        ).encode(),
        "customize.sh": (
            '#!/system/bin/sh\n'
            'set_perm "$MODPATH/action.sh" 0 0 0755\n'
            'set_perm "$MODPATH/bin/run-payload" 0 0 0755\n'
            'set_perm "$MODPATH/bin/driver-control" 0 0 0755\n'
        ).encode(),
        "bin/run-payload": (
            '#!/system/bin/sh\ncase "${1-}" in run) echo fixture ;; *) exit 64 ;; esac\n'
        ).encode(),
        "bin/driver-control": (
            '#!/system/bin/sh\n'
            "EXPECTED_SHA256='fixture'\n"
            "LOG_FILE='driver-webui.log'\n"
            'case "${1-}" in\n'
            '  run) mkfifo /tmp/fixture-fifo; tee "$LOG_FILE" </dev/null; '
            "echo '已执行 insmod'; echo '已跳过' ;;\n"
            '  log) echo "$LOG_FILE" ;;\n'
            '  *) exit 64 ;;\n'
            'esac\n'
        ).encode(),
        "payload/fixture-driver.sh": b"inert-driver-fixture\n",
        "webroot/index.html": '<button>刷入驱动</button>\n'.encode(),
        "webroot/app.js": (
            "const moduleInfo = { moduleDir: '/data/adb/modules/A.fixture-module' };\n"
            "const commands = Object.freeze({\n"
            "  driverRun: `/system/bin/sh ${moduleInfo.moduleDir}/bin/driver-control run`,\n"
            "  driverLog: `/system/bin/sh ${moduleInfo.moduleDir}/bin/driver-control log`,\n"
            "});\n"
            "window.ksu.spawn(commands.driverRun, '[]', '{}', 'fixtureCallback');\n"
            "window.ksu.exec(commands.driverLog, 'fixtureCallback');\n"
            "const events = ['stdout', 'stderr', 'exit', 'error'];\n"
        ).encode(),
    }


def write_source_and_zip(root: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    source = root / "A.fixture-module"
    release = root / "fixture.zip"
    source.mkdir()
    runtime = {"action.sh", "bin/run-payload", "bin/driver-control"}
    with zipfile.ZipFile(release, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            mode = 0o755 if name in runtime else 0o644
            target.chmod(mode)
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, data)
    return source, release


def run_verifier(root: Path, files: dict[str, bytes]) -> subprocess.CompletedProcess[str]:
    source, release = write_source_and_zip(root, files)
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--source",
            str(source),
            "--zip",
            str(release),
            "--mode",
            "manual-driver",
            "--profile",
            "minimal-action-manual-driver",
            "--action-helper",
            "bin/run-payload",
            "--module-id",
            "A.fixture-module",
            "--driver",
            str(source / "payload/fixture-driver.sh"),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class VerifyReleaseRegressionTests(unittest.TestCase):
    def verify(self, files: dict[str, bytes]) -> subprocess.CompletedProcess[str]:
        temporary = tempfile.TemporaryDirectory(prefix="verify-release-test-")
        self.addCleanup(temporary.cleanup)
        return run_verifier(Path(temporary.name), files)

    def test_valid_minimal_module_passes(self) -> None:
        result = self.verify(fixture_files())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("restores execute permission", result.stdout)

    def test_missing_post_install_permission_fails(self) -> None:
        files = fixture_files()
        files["customize.sh"] = files["customize.sh"].replace(
            b'set_perm "$MODPATH/bin/driver-control" 0 0 0755\n', b""
        )
        result = self.verify(files)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("KernelSU installs ordinary files as 0644", result.stdout)
        self.assertIn("bin/driver-control", result.stdout)

    def test_direct_action_helper_execution_fails(self) -> None:
        files = fixture_files()
        files["action.sh"] = (
            '#!/system/bin/sh\nMODDIR=${0%/*}\nexec "$MODDIR/bin/run-payload" run\n'
        ).encode()
        result = self.verify(files)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("must invoke bin/run-payload through /system/bin/sh", result.stdout)
        self.assertIn("directly executes a module bin helper", result.stdout)

    def test_direct_webui_helper_execution_fails(self) -> None:
        files = fixture_files()
        files["webroot/app.js"] = (
            "const moduleInfo = { moduleDir: '/data/adb/modules/A.fixture-module' };\n"
            "window.ksu.spawn(`${moduleInfo.moduleDir}/bin/driver-control run`, '[]', '{}', 'cb');\n"
            "window.ksu.exec(`${moduleInfo.moduleDir}/bin/driver-control log`, 'cb');\n"
            "const events = ['stdout', 'stderr', 'exit', 'error'];\n"
        ).encode()
        result = self.verify(files)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("WebUI must define fixed command /system/bin/sh", result.stdout)
        self.assertIn("directly receives a path/dynamic expression", result.stdout)

    def test_minimal_profile_rejects_extra_control_helper(self) -> None:
        files = fixture_files()
        files["bin/control"] = b"#!/system/bin/sh\necho unrequested\n"
        files["customize.sh"] += b'set_perm "$MODPATH/bin/control" 0 0 0755\n'
        files["webroot/app.js"] += (
            "const extra = `${moduleInfo.moduleDir}/bin/control`;\n"
        ).encode()
        result = self.verify(files)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("minimal profile contains unrequested", result.stdout)
        self.assertIn("outside the selected profile allowlist", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

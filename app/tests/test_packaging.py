"""Bundled assets and dependencies the desktop build relies on (no build, no I/O beyond reads)."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_center import lcd_preview, ui
from control_center.presentation import ICONS

ASSETS = ROOT / "assets"
ART_BYTES = 120 * 120 * 2


def requirement_lines(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


class RequirementsTests(unittest.TestCase):
    def test_runtime_requirements_pin_pillow_and_requests(self):
        lines = requirement_lines("requirements.txt")
        self.assertIn("Pillow==12.3.0", lines)
        self.assertTrue(any(re.fullmatch(r"requests==\d+(\.\d+)+", line) for line in lines), lines)

    def test_desktop_requirements_include_runtime_ones_once(self):
        lines = requirement_lines("requirements-desktop.txt")
        self.assertIn("-r requirements.txt", lines)
        self.assertFalse([line for line in lines if line.lower().startswith("pillow")],
                         "Pillow comes from requirements.txt only")


class AssetTests(unittest.TestCase):
    def test_every_button_icon_has_all_sizes(self):
        for name in ICONS:
            if not name:
                continue
            for size in (16, 20, 26):
                with self.subTest(icon=name, size=size):
                    self.assertTrue((ASSETS / "handoff-icons" / f"{name}-{size}.png").is_file())

    def test_fonts_and_licences(self):
        for name in ("Montserrat.ttf", "Archivo.ttf", "OFL-Montserrat.txt", "OFL-Archivo.txt"):
            with self.subTest(name=name):
                path = ASSETS / "fonts" / name
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

    def test_art_fixtures_are_wire_sized(self):
        for name in ("art-den-120.rgb565", "art-bright-120.rgb565"):
            with self.subTest(name=name):
                self.assertEqual((ASSETS / "fixtures" / name).stat().st_size, ART_BYTES)

    def test_renderer_and_ui_asset_paths_resolve(self):
        self.assertEqual(lcd_preview.ASSETS.resolve(), ASSETS.resolve())
        self.assertTrue(lcd_preview.FONT_PATH.is_file())
        self.assertTrue(lcd_preview.ICON_DIR.is_dir())
        self.assertEqual(ui.APP_DIR.resolve(), ROOT.resolve())
        for name in ui.BUNDLED_FONTS:
            self.assertTrue((ui.FONT_DIR / name).is_file())

    def test_smoke_and_tray_assets_resolve(self):
        import standalone
        self.assertTrue((ui.APP_DIR / standalone.SMOKE_ART).is_file())
        self.assertTrue((ui.APP_DIR / "assets" / "lcd-icons" / "ok-white.png").is_file())
        for theme in standalone.TRAY_THEMES:
            for present in (True, False):
                self.assertTrue(standalone.tray_icon_file(theme, present, ui.APP_DIR).is_file())
                self.assertTrue(standalone.tray_png(theme, present, ui.APP_DIR).is_file())


class AppIconPackagingTests(unittest.TestCase):
    """APP_ICON.md items 1, 2 and 7: the designer's files, their frames, the exe icon and the
    Start-menu shortcut. Reads only; the tray .ico loads create and destroy HICONs, no window."""

    APP_ICON = ASSETS / "app-icon"

    def test_the_ico_frame_inventory(self):
        from PIL import Image
        expected = {"nano-d-app.ico": [16, 20, 24, 32, 40, 48, 64, 256]}
        for theme in ("dark", "light"):
            for state in ("connected", "missing"):
                expected[f"nano-d-tray-{theme}-{state}.ico"] = [16, 20, 24, 32]
        self.assertEqual(sorted(path.name for path in (self.APP_ICON / "ico").glob("*.ico")), sorted(expected))
        for name, sizes in expected.items():
            with self.subTest(ico=name), Image.open(self.APP_ICON / "ico" / name) as image:
                self.assertEqual(sorted(image.info["sizes"]), [(size, size) for size in sizes])
        for name in ("nano-d-app-256.png", "nano-d-app-32.png"):
            with Image.open(self.APP_ICON / "png" / name) as image:
                size = int(name.rsplit("-", 1)[1].split(".")[0])
                self.assertEqual(image.size, (size, size))

    def test_the_build_embeds_the_app_icon(self):
        script = (ROOT / "Build-Desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("$appIcon = Join-Path $PSScriptRoot 'assets\\app-icon\\ico\\nano-d-app.ico'", script)
        build = next(line for line in script.splitlines() if "-m PyInstaller" in line)
        self.assertIn("--icon $appIcon", build)
        self.assertIn("--add-data $assets", build)          # assets\app-icon ships with the bundle

    def test_the_start_menu_shortcut_uses_the_exes_icon(self):
        # The task-context step creates the shortcut of the identity being installed (Desk Dial.lnk, or the
        # old name's for a rollback bundle), pointing at that identity's installed exe and its icon 0.
        script = (ROOT / "Install-UserData.ps1").read_text(encoding="utf-8")
        self.assertIn("$shortcut.TargetPath = $p.exe", script)
        self.assertIn("$shortcut.IconLocation = $p.exe + ',0'", script)
        self.assertLess(script.index("$shortcut.IconLocation"), script.index("$shortcut.Save()"))
        install = (ROOT / "Install-Desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("$shortcutPath = Join-Path $programsMenu $id.shortcut", install)
        self.assertIn("shortcut = $shortcutPath; shortcutDescription = $id.shortcutDescription", install)

    def test_smoke_app_icons(self):
        import standalone
        detail = standalone.smoke_app_icons()
        self.assertEqual(detail["frames"]["nano-d-app.ico"], [16, 20, 24, 32, 40, 48, 64, 256])
        self.assertEqual(detail["trayIconsLoaded"], 4)
        self.assertTrue(detail["appIconLoaded"], "Tk windows get the app .ico's frames through LoadImageW")
        self.assertGreaterEqual(detail["smallIconSize"], 16)
        self.assertEqual(detail["exeIcon"], {"checked": False})
        # The frozen branch reads the running exe's embedded icons (python.exe has one here).
        frozen = standalone.smoke_app_icons(frozen=True, executable=sys.executable)
        self.assertTrue(frozen["exeIcon"]["checked"])
        self.assertGreaterEqual(frozen["exeIcon"]["icons"], 1)

    def test_smoke_app_icons_fails_on_a_missing_file_a_wrong_frame_set_or_a_failed_load(self):
        import shutil
        import tempfile
        import standalone
        from PIL import Image

        class NoLoad:
            def small_icon_size(self): return 16
            def load(self, path, size): return None
            def destroy(self, handle): return True
        class NoAppLoad(NoLoad):
            def __init__(self): self.loads = []
            def load(self, path, size):
                self.loads.append(Path(path).name)
                return None if Path(path).name == "nano-d-app.ico" else 1
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            shutil.copytree(self.APP_ICON, bundle / "assets" / "app-icon")
            with self.assertRaisesRegex(RuntimeError, "LoadImageW"):
                standalone.smoke_app_icons(bundle, api=NoLoad(), frozen=False)
            app_only = NoAppLoad()
            with self.assertRaisesRegex(RuntimeError, "LoadImageW returned no icon for nano-d-app.ico"):
                standalone.smoke_app_icons(bundle, api=app_only, frozen=False)
            self.assertEqual(len(app_only.loads), 5, "the 4 tray .ico files, then the app .ico")
            tray = bundle / "assets" / "app-icon" / "ico" / "nano-d-tray-light-missing.ico"
            Image.new("RGBA", (32, 32)).save(tray, sizes=[(16, 16), (32, 32)])
            with self.assertRaisesRegex(RuntimeError, "frames"):
                standalone.smoke_app_icons(bundle, frozen=False)
            (bundle / "assets" / "app-icon" / "png" / "nano-d-app-32.png").unlink()
            with self.assertRaisesRegex(RuntimeError, "missing icon files"):
                standalone.smoke_app_icons(bundle, frozen=False)


class InstallScriptTests(unittest.TestCase):
    """Install-Desktop.ps1, Install-UserData.ps1 and Build-Desktop.ps1, read only (never run)."""

    PINS = {"desktop-dist-v2": "95909AAE4AA4852F5E4954EEED329E513FC474BC50E08B8DCD6655CE410A123D",
            "desktop-dist-v3": "90A235527274656AE9F4C5E49D99625D0E125A1466D9952DC47A0DD882E8FE19",
            "desktop-dist-v4": "63047D1C7C181C456B0AEE6E825B21326899538164E6AFFECB3800785C0C44A5",
            "desktop-dist-v5": "0BF15DB86F5376F763193474457DEDFCB04D8ECEBC401E396E966EB668C2D210",
            "desktop-dist-v6": "2F79FDDA9EE2968484F78D043F11E1A341FB4C0C9F0350AD30821523B6B61C0F"}
    # rename-desk-dial.md sections 1 and 11.6: the identity each bundle installs as.
    IDENTITIES = {"DeskDial": {"exe": "DeskDial.exe", "program": "Programs\\DeskDial", "home": "DeskDial",
                               "task": "Desk Dial", "shortcut": "Desk Dial.lnk"},
                  "NanoDControlCenter": {"exe": "NanoDControlCenter.exe", "program": "Programs\\NanoDControlCenter",
                                         "home": "NanoDControlCenter", "task": "NanoD Control Center",
                                         "shortcut": "Nano_D++ Control Center.lnk"}}

    def script(self, name="Install-Desktop.ps1"):
        return (ROOT / name).read_text(encoding="utf-8")

    def identities(self):
        script = self.script()
        block = script[script.index("$identities = @{"):script.index("$bundleIdentities = @{")]
        found = {}
        for name, body in re.findall(r"'(\w+)' = @\{(.*?)\}", block, re.S):
            found[name] = dict(re.findall(r"(\w+) = '((?:[^']|'')*)'", body))
        return found

    def test_every_rollback_bundle_is_pinned_and_documented(self):
        script = self.script()
        self.assertEqual(dict(re.findall(r"'(desktop-dist-v\d)' = '([0-9A-F]{64})'", script)), self.PINS)
        for bundle, digest in self.PINS.items():
            with self.subTest(bundle=bundle):
                self.assertEqual(script.count(digest), 2, "the header's rollback line and the pin")
                self.assertIn(f"Install-Desktop.ps1 -Bundle {bundle} -Mirror", script)

    def test_the_identity_table_names_both_apps(self):
        """Pinned v2-v6 install as NanoD Control Center, every other bundle as Desk Dial (forward and rollback)."""
        found = self.identities()
        self.assertEqual(set(found), set(self.IDENTITIES))
        for name, want in self.IDENTITIES.items():
            with self.subTest(identity=name):
                self.assertEqual({key: found[name][key] for key in want}, want)
        self.assertEqual(found["DeskDial"]["taskDescription"],
                         "Desk Dial: the knob''s Sonos, Apple Music and Windows companion. Runs in the signed-in user session.")
        self.assertTrue(found["DeskDial"]["shortcutDescription"].startswith("Open Desk Dial settings;"))
        script = self.script()
        table = script[script.index("$bundleIdentities = @{"):script.index("function Get-SmokeReportProblem")]
        self.assertEqual(dict(re.findall(r"'(desktop-dist-v\d)' = '(\w+)'", table)),
                         {bundle: "NanoDControlCenter" for bundle in self.PINS})
        self.assertIn("$idName = 'DeskDial'", script)                       # any other bundle
        # The app's own paths are the Desk Dial identity's (control_center.paths).
        from control_center import paths
        self.assertEqual((paths.HOME_NAME, paths.LEGACY_HOME_NAME), ("DeskDial", "NanoDControlCenter"))

    def test_a_new_bundle_needs_its_passing_smoke_report_before_anything_changes(self):
        script = self.script()
        gate = script.index('Get-SmokeReportProblem (Join-Path $env:LOCALAPPDATA "$($id.home)\\logs\\smoke-test.json") $bundleExe')
        self.assertLess(script.index("if ($pinned) {"), gate)
        for change in ("Get-Process -Name 'DeskDial', 'NanoDControlCenter'", "New-Item -ItemType Directory -Path $install",
                       "Remove-Item -LiteralPath $stale", "Copy-Item -Destination $install", "Invoke-UserDataStep 'install'",
                       "Register-ScheduledTask -TaskName $id.task"):
            with self.subTest(step=change):
                self.assertLess(gate, script.index(change))
        for condition in ("$report.passed -ne $true", "$report.frozen -ne $true",
                          "[StringComparison]::OrdinalIgnoreCase", "LastWriteTimeUtc",
                          "[double]$report.timestamp -lt $built"):
            self.assertIn(condition, script)
        header = script[:script.index("[string]$Bundle")]
        self.assertIn("--smoke-test", header, "the documented install steps run the smoke test first")
        self.assertIn("desktop-dist-v7\\DeskDial\\DeskDial.exe --smoke-test", header)
        self.assertIn("%LOCALAPPDATA%\\DeskDial\\logs\\smoke-test.json", header)
        self.assertLess(header.index("--smoke-test"), header.index("Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror -DryRun"))
        self.assertLess(header.index("-Mirror -DryRun"), header.index("run\n    # Install-Desktop.ps1 -Bundle desktop-dist-v7 -Mirror;"))
        self.assertIn("--smoke-test --headless", header)
        self.assertIn("[string]$Bundle = 'desktop-dist-v7'", script)

    def test_the_smoke_report_path_moves_with_the_app(self):
        """rename-desk-dial.md 11.9: standalone.py writes the report where the installer reads it."""
        import os
        import standalone  # noqa: F401  (main() builds its logs folder from control_center.paths)
        from unittest.mock import patch
        from control_center import paths
        source = (ROOT / "standalone.py").read_text(encoding="utf-8")
        self.assertIn("logs = paths.logs_dir()", source)
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}):
            self.assertEqual(paths.logs_dir(), Path(r"C:\Users\someone\AppData\Local\DeskDial\logs"))
        self.assertEqual(self.identities()["DeskDial"]["home"], paths.HOME_NAME)

    def test_either_companion_running_refuses_the_install(self):
        script = self.script()
        check = next(line for line in script.splitlines() if "Get-Process -Name" in line)
        self.assertIn("-Name 'DeskDial', 'NanoDControlCenter'", check)
        refusal = next(line for line in script.splitlines() if "$running.Count -gt 0" in line)
        self.assertIn("Quit Desk Dial (or the old Nano_D++ Control Center) from the tray before updating", refusal)
        build = self.script("Build-Desktop.ps1")
        self.assertIn("Get-Process -Name DeskDial, NanoDControlCenter -ErrorAction SilentlyContinue", build)

    def test_the_dry_run_changes_nothing(self):
        """14.2 step 4 / 14.4 item 2: -DryRun runs every check, writes the plan and exits before any change."""
        script = self.script()
        self.assertIn("[switch]$DryRun", script)
        start = script.index("if ($DryRun) {\n    # Names and sizes only")
        first_change = script.index("New-Item -ItemType Directory -Path $install -Force")
        self.assertLess(start, first_change)
        for check in ("Stop-Install \"Build the executable first", "$bundleExeHash -ne $pinnedBundles[$bundleName]",
                      "Get-SmokeReportProblem (Join-Path", "Get-Process -Name 'DeskDial', 'NanoDControlCenter'"):
            self.assertLess(script.index(check), start, check)
        block = script[start:first_change]
        for verb in ("Copy-Item", "Move-Item", "Remove-Item", "New-Item", "Register-ScheduledTask",
                     "Unregister-ScheduledTask", "Disable-ScheduledTask", "Invoke-UserDataStep", "Out-File"):
            self.assertNotIn(verb, block, verb)
        self.assertEqual(block.count("Set-Content"), 1)
        self.assertIn("Set-Content -LiteralPath $planPath", block)
        self.assertIn("$planPath = Join-Path $diagnostics 'desktop-install-plan.json'", block)
        self.assertIn("exit 1", block)
        self.assertTrue(block.rstrip().endswith("exit 0\n}") or block.rstrip().endswith("exit 0\r\n}"), block[-80:])
        for field in ("identity = $id.name", "replaces = $other.name", "refusals = @($refusals)", "register = $id.task",
                      "unregister = $other.task", "moveTo = $programBackup", "bytes = $file.Length",
                      "writtenBeforeMigration = @()"):
            self.assertIn(field, block)
        self.assertNotIn("Get-Content", block, "a dry run reads names and sizes only, never file contents")
        # Refusals are recorded by the dry run and thrown by a real install.
        self.assertIn("if ($DryRun) { $refusals.Add($Message) } else { throw $Message }", script)

    def test_install_desktop_is_never_run_by_a_test(self):
        """Review finding RN-R4: Install-Desktop.ps1 is edited, never run, even as a copy with -DryRun (it reads the
        real process list, Task Scheduler and Start menu whatever LOCALAPPDATA says). No test or test tool starts it;
        the static tests above and Install-UserData.ps1's temporary-folder runs are the evidence, and the rename
        record lists no run of it as a check (the dry run is the supervised runbook's step 9a)."""
        import ast
        runners = {"run", "Popen", "call", "check_call", "check_output", "system", "startfile", "spawnv", "execv"}
        sources = sorted((ROOT / "tests").rglob("*.py"))
        self.assertIn(Path(__file__).resolve(), [path.resolve() for path in sources])
        offenders = []
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name in runners and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                                           and "Install-Desktop" in c.value for c in ast.walk(node)):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], "a test must never run Install-Desktop.ps1")
        record = (ROOT / "design-reference" / "ui-v2-analysis" / "rename-desk-dial.md").read_text(encoding="utf-8")
        record = record[record.index("## 15. Implementation record"):]
        checks = record[record.index("Checks run:"):record.index("Process breach (review finding RN-R4)")]
        self.assertNotIn("Install-Desktop.ps1 -DryRun", checks)
        self.assertNotRegex(" ".join(checks.split()), r"Install-Desktop\.ps1[^.;]*\b(?:ran|run against|a copy)\b")
        self.assertIn("belongs to the supervised runbook (`firmware\\BUILD-cc5.4.md` step 9a)", " ".join(checks.split()))
        breach = " ".join(record[record.index("Process breach (review finding RN-R4)"):].split())
        self.assertIn("Those runs are not evidence for this release", breach)

    def test_seeds_are_staged_only_and_applied_after_the_migration(self):
        """14.3: a first Desk Dial install must not seed the data folder before the migration copies the live files."""
        script = self.script()
        self.assertNotRegex(script, r"Copy-Item[^\n]*-Destination \$data\b")
        self.assertNotRegex(script, r"Join-Path \$data \$name")
        self.assertIn("if (Test-Path -LiteralPath $seed) { Copy-Item -LiteralPath $seed -Destination $staged -Force }", script)
        self.assertIn("elseif (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Force }", script)
        user = self.script("Install-UserData.ps1")
        body = user[user.index("$stage = 'plan'"):]
        order = [body.index(s) for s in ("$stage = 'program'\n    if (-not (Test-Path -LiteralPath $p.exe)",
                                         "Copy-OldHome $p.migrateFrom $p.home", "$stage = 'seeds'",
                                         "(Test-Path -LiteralPath $inputFile) -and -not (Test-Path -LiteralPath $outputFile)",
                                         "$shortcut.Save()")]
        self.assertEqual(order, sorted(order))

    def test_the_migration_copies_the_whole_old_home_once_and_by_hash(self):
        """Lead ruling on the rename, item 3: the whole home (data\\, logs\\, the root .bin files), copied once,
        hash verified, the old home only read, in the task context (not the app)."""
        user = self.script("Install-UserData.ps1")
        copy = user[user.index("function Copy-OldHome"):user.index("$stage = 'plan'")]
        self.assertIn("Get-ChildItem -LiteralPath $root -File -Recurse -Force", copy)
        self.assertIn("if (Test-Path -LiteralPath $record) { return", copy)          # once
        self.assertIn("$partial = \"$target.migrating\"", copy)
        self.assertLess(copy.index("Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName"),
                        copy.index("Move-Item -LiteralPath $partial -Destination $target"))
        self.assertNotRegex(copy, r"(Remove-Item|Move-Item|Set-Content|Copy-Item)[^\n]*\$file\.FullName -Destination \$root")
        self.assertNotIn("Get-Content", copy, "never file contents")
        for removal in re.findall(r"Remove-Item[^\n]*", copy):
            self.assertIn("-LiteralPath $path", removal, "only files this run created are removed")
        script = self.script()
        self.assertIn("if ($id.name -eq 'DeskDial') { $migrateFrom = Join-Path $env:LOCALAPPDATA $other.home }", script)
        # The app itself never reads or migrates the old home (control_center.paths, standalone.py).
        app_sources = [ROOT / "standalone.py", *(ROOT / "control_center").rglob("*.py")]
        for path in app_sources:
            text = path.read_text(encoding="utf-8")
            if path.name == "paths.py":
                self.assertEqual(text.count('"NanoDControlCenter"'), 1, "LEGACY_HOME_NAME only")
                continue
            for line in text.splitlines():
                if "NanoDControlCenter" in line:
                    with self.subTest(file=path.name, line=line.strip()[:80]):
                        self.assertRegex(line, r"NanoDControlCenter\.(App|Show)'|TRAY_NAME = 'NanoDControlCenter'")

    def test_the_other_name_is_retired_only_after_the_new_install_verified(self):
        script = self.script()
        order = [script.index(s) for s in (
            "throw \"Bundle verification failed: $relative\"", "$userData = Invoke-UserDataStep 'install'",
            "Register-ScheduledTask -TaskName $id.task", "Unregister-ScheduledTask -TaskName $other.task -Confirm:$false }",
            "Invoke-UserDataStep 'cleanup'", "'desktop-installation.json'")]
        self.assertEqual(order, sorted(order))
        self.assertIn("$programBackup = Join-Path $PSScriptRoot \"backups\\desktop-program-$($other.name)-$stamp\"", script)
        self.assertIn("$taskName = 'Desk Dial Data Setup ' + [Guid]::NewGuid().ToString('N')", script)
        self.assertNotIn("NanoD Data Setup", script)
        user = self.script("Install-UserData.ps1")
        cleanup = user[user.index("if ($Step -eq 'cleanup') {"):user.index("$stage = 'program'\n    if (-not")]
        self.assertIn("Move-Item -LiteralPath $p.otherProgram -Destination $p.programBackup", cleanup)
        self.assertNotRegex(cleanup, r"Remove-Item[^\n]*otherProgram")          # moved, never deleted
        self.assertIn("Remove-Item -LiteralPath $p.otherShortcut -Force", cleanup)
        record = script[script.index("[ordered]@{ executable = $exe"):]
        for field in ("sha256 = (Get-FileHash -LiteralPath $exe).Hash", "task = $id.task", "taskUnregistered = $otherTaskFound",
                      "programMovedTo"):
            self.assertIn(field, record)

    def test_the_build_explains_the_deferred_smoke_test(self):
        script = self.script("Build-Desktop.ps1")
        self.assertNotIn("single-instance handling would otherwise exit early", script)
        self.assertIn("runs before the\n    # single-instance mutex", script)

    def test_v7_builds_into_new_folders_and_refuses_every_rollback_bundle(self):
        script = self.script("Build-Desktop.ps1")
        self.assertIn("[string]$Dist = 'desktop-dist-v7'", script)
        self.assertIn("[string]$Work = 'desktop-build-v7'", script)
        refused = re.search(r"\$rollbackFolders = @\(([^)]*)\)", script).group(1)
        for version in (2, 3, 4, 5, 6):
            with self.subTest(version=version):
                self.assertIn(f"'desktop-dist-v{version}'", refused)
                self.assertIn(f"'desktop-build-v{version}'", refused)
        self.assertNotIn("v7", refused)
        # Every pinned rollback bundle is refused by the build.
        self.assertEqual(set(re.findall(r"'desktop-dist-(v\d)'", refused)),
                         {bundle.rsplit("-", 1)[1] for bundle in self.PINS})

    def test_the_build_is_desk_dial_with_a_version_resource(self):
        """rename-desk-dial.md 3.1 and 11.10: --name DeskDial, the version resource, and an old-name build moved aside."""
        script = self.script("Build-Desktop.ps1")
        build = next(line for line in script.splitlines() if "-m PyInstaller" in line)
        self.assertIn("--name DeskDial --icon $appIcon --version-file $versionFile ", build)
        self.assertNotIn("NanoDControlCenter", build)
        self.assertIn("$versionFile = Join-Path $PSScriptRoot 'desktop-version.txt'", script)
        self.assertIn("$builtExe = Join-Path $distRoot 'DeskDial\\DeskDial.exe'", script)
        self.assertIn("(Get-Item -LiteralPath $builtExe).VersionInfo.FileDescription -ne 'Desk Dial'", script)
        moved = script.index("Move-Item -LiteralPath $oldNameBuild -Destination $superseded")
        self.assertLess(script.index("if ($rollbackFolders -contains $leaf) { throw"), moved)
        self.assertLess(moved, script.index("-m PyInstaller"))
        self.assertNotRegex(script, r"Remove-Item[^\n]*oldNameBuild")
        text = (ROOT / "desktop-version.txt").read_text(encoding="utf-8")
        for key, value in (("FileDescription", "Desk Dial"), ("ProductName", "Desk Dial"), ("InternalName", "DeskDial"),
                           ("OriginalFilename", "DeskDial.exe"), ("FileVersion", "7.0.0.0")):
            self.assertIn(f"StringStruct('{key}', '{value}')", text)
        try:
            from PyInstaller.utils.win32 import versioninfo
        except ImportError:
            return   # the desktop build venv parses it below; the text checks above still hold
        info = versioninfo.load_version_info_from_text_file(str(ROOT / "desktop-version.txt"))
        strings = {s.name: s.val for s in info.kids[0].kids[0].kids}
        self.assertEqual((strings["FileDescription"], strings["ProductName"], strings["OriginalFilename"]),
                         ("Desk Dial", "Desk Dial", "DeskDial.exe"))

    def test_the_build_runs_its_own_smoke_test_headless(self):
        script = self.script("Build-Desktop.ps1")
        self.assertIn("-ArgumentList '--smoke-test', '--headless'", script)
        self.assertNotIn("-ArgumentList '--smoke-test' -", script)

    def test_the_build_bundles_the_carousel_modules(self):
        build = next(line for line in self.script("Build-Desktop.ps1").splitlines() if "-m PyInstaller" in line)
        for module in ("carousel", "carousel_render", "window_labels", "window_facts"):
            with self.subTest(module=module):
                self.assertIn(f"--hidden-import control_center.{module} ", build)

    def test_the_build_bundles_the_v7_modules(self):
        """The alive floating knob, the music overlay and the whole NanoD-stage package (DESKTOP_STAGE)."""
        build = next(line for line in self.script("Build-Desktop.ps1").splitlines() if "-m PyInstaller" in line)
        for module in ("alive_lights", "preview_lights", "music_overlay", "scene_music", "render_music",
                       "queue_context", "simulation", "presentation", "stage", "stage.scenes"):
            with self.subTest(module=module):
                self.assertIn(f"--hidden-import control_center.{module} ", build)
                path = ROOT / "control_center" / module.replace(".", "/")
                self.assertTrue(path.with_suffix(".py").is_file() or (path / "__init__.py").is_file(), module)
        self.assertIn("--collect-submodules control_center.stage ", build)

    def test_the_native_verifier_reads_the_installed_name(self):
        """rename-desk-dial.md 14.2 step 0: Verify-NativeDesktop.ps1 checks whichever companion is installed."""
        script = (ROOT / "diagnostics" / "Verify-NativeDesktop.ps1").read_text(encoding="utf-8")
        for path in ("'Programs\\DeskDial\\DeskDial.exe'", "'DeskDial\\logs'",
                     "'Programs\\NanoDControlCenter\\NanoDControlCenter.exe'", "'NanoDControlCenter\\logs'"):
            self.assertIn(path, script)
        self.assertLess(script.index("'Programs\\DeskDial\\DeskDial.exe'"), script.index("'Programs\\NanoDControlCenter\\"))
        self.assertIn("desktop-installation.json", script)


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell")
class UserDataStepSandboxTests(unittest.TestCase):
    """Install-UserData.ps1 run for real against temporary folders only: every path it touches comes from the
    plan file this test writes (no %LOCALAPPDATA%, no Start menu, no task). Never Install-Desktop.ps1."""

    POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

    def setUp(self):
        import tempfile
        if not self.POWERSHELL.is_file():
            self.skipTest("Windows PowerShell is not available")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.old, self.new = base / "old-home", base / "new-home"
        self.program, self.other_program = base / "programs" / "new-app", base / "programs" / "old-app"
        self.seeds, self.backups, self.menu = base / "seeds", base / "backups", base / "menu"
        for folder in (self.program, self.other_program, self.seeds, self.backups, self.menu):
            folder.mkdir(parents=True)
        (self.program / "App.exe").write_bytes(b"MZ new app")
        (self.other_program / "Old.exe").write_bytes(b"MZ old app")
        (self.other_program / "_internal").mkdir()
        (self.other_program / "_internal" / "lib.dll").write_bytes(b"dll")
        (self.menu / "Old.lnk").write_bytes(b"stale shortcut")
        names = ("data\\settings.json", "data\\credentials.bin", "queue-recovery.bin", "shuffle-restore.bin",
                 "logs\\app.log", "logs\\smoke-test.json", "backups\\control-center-inventory-1.json")
        self.old_files = {name: f"content-marker-{i}-{'x' * i}".encode() for i, name in enumerate(names)}
        for name, content in self.old_files.items():
            (self.old / name).parent.mkdir(parents=True, exist_ok=True)
            (self.old / name).write_bytes(content)
        (self.new / "logs").mkdir(parents=True)
        (self.new / "logs" / "smoke-test.json").write_bytes(b"new-home-smoke")   # the new exe's own smoke report
        (self.seeds / "settings.json").write_bytes(b"seed-settings")
        (self.seeds / "credentials.bin").write_bytes(b"seed-grant")

    def plan(self, migrate=True, exe_sha=None):
        import hashlib
        import json
        exe = self.program / "App.exe"
        plan = {"identity": "DeskDial", "program": str(self.program), "exe": str(exe),
                "exeSha256": exe_sha or hashlib.sha256(exe.read_bytes()).hexdigest().upper(),
                "home": str(self.new), "data": str(self.new / "data"), "seeds": str(self.seeds),
                "seedNames": ["settings.json", "credentials.bin"], "migrateFrom": str(self.old) if migrate else None,
                "shortcut": str(self.menu / "New.lnk"), "shortcutDescription": "Open Desk Dial settings; test",
                "otherShortcut": str(self.menu / "Old.lnk"), "otherProgram": str(self.other_program),
                "programBackup": str(self.backups / "desktop-program-old-20260926T000000Z")}
        path = Path(self.temp.name) / "install-step.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def run_step(self, plan, step="install"):
        import json
        import subprocess
        report = Path(self.temp.name) / f"report-{step}.json"
        if report.exists():
            report.unlink()
        done = subprocess.run([str(self.POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(ROOT / "Install-UserData.ps1"), "-Plan", str(plan), "-Step", step,
                               "-Report", str(report)], capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return done.returncode, json.loads(report.read_text(encoding="utf-8-sig"))

    def listing(self, root):
        import hashlib
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def test_install_migrates_once_by_hash_and_the_old_home_wins_over_the_seeds(self):
        import json
        before = self.listing(self.old)
        code, report = self.run_step(self.plan())
        self.assertEqual((code, report["passed"]), (0, True), report)
        self.assertEqual(self.listing(self.old), before, "the old home is only read")
        for name, content in self.old_files.items():
            if name == "logs\\smoke-test.json":
                continue
            self.assertEqual((self.new / name).read_bytes(), content, name)     # data\, logs\, backups\, root .bin
        self.assertEqual((self.new / "logs" / "smoke-test.json").read_bytes(), b"new-home-smoke", "an existing file is kept")
        self.assertEqual(list(self.new.rglob("*.migrating")), [])
        record = json.loads((self.new / "migration.json").read_text(encoding="utf-8-sig"))
        files = {f["name"]: f for f in record["files"]}
        self.assertEqual(set(files), set(self.old_files))
        self.assertEqual(files["logs\\smoke-test.json"]["copied"], False)
        for name in set(self.old_files) - {"logs\\smoke-test.json"}:
            self.assertEqual((files[name]["copied"], files[name]["hashMatch"], files[name]["bytes"]),
                             (True, True, len(self.old_files[name])), name)
        text = (self.new / "migration.json").read_text(encoding="utf-8-sig")
        for content in self.old_files.values():
            self.assertNotIn(content.decode(), text, "names and sizes only, never contents")
        # 14.3: the seeds never replace the migrated live files.
        self.assertEqual([(f["name"], f["copied"]) for f in report["files"]], [("settings.json", False), ("credentials.bin", False)])
        self.assertEqual((self.new / "data" / "settings.json").read_bytes(), self.old_files["data\\settings.json"])
        self.assertTrue((self.menu / "New.lnk").is_file())
        # Once: a second install never copies again, so a file the app removed does not come back.
        (self.new / "queue-recovery.bin").unlink()
        code, report = self.run_step(self.plan())
        self.assertEqual((code, report["migration"]["skipped"]), (0, "already migrated"), report)
        self.assertFalse((self.new / "queue-recovery.bin").exists())

    def test_a_program_the_user_cannot_see_stops_everything(self):
        code, report = self.run_step(self.plan(exe_sha="0" * 64))
        self.assertEqual((code, report["passed"], report["stage"]), (1, False, "program"), report)
        self.assertFalse((self.new / "data").exists())
        self.assertFalse((self.new / "migration.json").exists())
        self.assertFalse((self.menu / "New.lnk").exists())

    def test_a_rollback_install_seeds_only_where_missing_and_never_migrates(self):
        code, report = self.run_step(self.plan(migrate=False))
        self.assertEqual((code, report["passed"], report["migration"]), (0, True, None), report)
        self.assertEqual([(f["name"], f["copied"]) for f in report["files"]], [("settings.json", True), ("credentials.bin", True)])
        self.assertFalse((self.new / "migration.json").exists())

    def test_cleanup_moves_the_other_program_folder_and_removes_its_shortcut(self):
        before = self.listing(self.other_program)
        code, report = self.run_step(self.plan(), step="cleanup")
        self.assertEqual((code, report["passed"], report["shortcutRemoved"]), (0, True, True), report)
        backup = self.backups / "desktop-program-old-20260926T000000Z"
        self.assertEqual(Path(report["programMovedTo"]), backup)
        self.assertFalse(self.other_program.exists())
        self.assertEqual(self.listing(backup), before, "moved whole, never deleted")
        self.assertFalse((self.menu / "Old.lnk").exists())


class Artwork2PackagingTests(unittest.TestCase):
    """artwork2 needs Pillow's JPEG encoder and decoder in the frozen build (ARTWORK2.md section 5)."""

    def test_pillow_has_the_jpeg_codec(self):
        from PIL import features, JpegImagePlugin  # noqa: F401  (the plugin the frozen build must bundle)
        self.assertTrue(features.check_codec("jpg"))

    def test_smoke_artwork2_encodes_decodes_and_draws(self):
        import standalone
        from control_center.presentation import COVER_MAX_BYTES, ICON_BYTES
        detail = standalone.smoke_artwork2()
        self.assertLessEqual(detail["jpegBytes"], COVER_MAX_BYTES)
        self.assertEqual((detail["rgb565Bytes"], detail["iconBytes"]), (ART_BYTES, ICON_BYTES))

    def test_smoke_test_runs_the_artwork2_check_and_fails_on_any_failure(self):
        # No Tk here: a failing Tk root must still leave the artwork2 result and a non-zero exit.
        import json
        import tempfile
        from unittest.mock import patch
        import standalone
        with tempfile.TemporaryDirectory() as temp, \
                patch("tkinter.Tk", side_effect=RuntimeError("no Tk in this test")), \
                patch("control_center.ui.register_fonts", return_value={}):
            out = Path(temp) / "logs"
            self.assertEqual(standalone.run_smoke_test(out, ui=False), 1)
            report = json.loads((out / "smoke-test.json").read_text(encoding="utf-8"))
        checks = report["checks"]
        self.assertFalse(report["passed"])
        for key in ("passed", "frozen", "executable", "timestamp"):   # what Install-Desktop.ps1's gate reads
            self.assertIn(key, report)
        self.assertEqual(report["executable"], sys.executable)
        self.assertIsInstance(report["timestamp"], float)
        self.assertFalse(checks["tk"]["passed"])
        for name in ("art", "lcd", "icons", "fontsPil", "artwork2", "appIcons"):
            with self.subTest(check=name):
                self.assertTrue(checks[name]["passed"], checks[name])
        self.assertLessEqual(checks["artwork2"]["detail"]["jpegBytes"], 32768)

    def test_a_smoke_run_writes_only_its_report_in_the_desk_dial_home(self):
        """rename-desk-dial.md 14.2 step 5: a smoke run creates nothing in DeskDial\\data (the migration
        copies only missing files, so a smoke file there would shadow the user's) and never reads or
        writes the old home."""
        import os
        import tempfile
        from unittest.mock import patch
        import standalone
        from control_center import paths
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCALAPPDATA": temp}), \
                patch("tkinter.Tk", side_effect=RuntimeError("no Tk in this test")), \
                patch("control_center.ui.register_fonts", return_value={}):
            standalone.run_smoke_test(paths.logs_dir(), ui=False)
            created = sorted(p.relative_to(temp).as_posix() for p in Path(temp).rglob("*") if p.is_file())
        self.assertEqual(created, ["DeskDial/logs/smoke-test.json"])


if __name__ == "__main__":
    unittest.main()

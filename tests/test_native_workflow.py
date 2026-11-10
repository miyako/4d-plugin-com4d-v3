"""Execute native phases only behind a closed PATH of offline tool doubles."""

import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

from version_support import Fixture, ROOT, cwd, original, source
import native


STUB = r'''#!PYTHON
import base64, json, os, pathlib, plistlib, shutil, sys
tool, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["NATIVE_LOG"], "a") as stream:
    stream.write(json.dumps([tool, *args]) + "\n")
if os.environ.get("FAIL_TOOL") == tool:
    sys.exit(23)
contents = pathlib.Path("test/Plugins/COM4D.bundle/Contents")
if tool == "xcodebuild":
    assert args == [
        "-project", "COM4D.xcodeproj", "-target", "COM4D", "-configuration", "Default",
        "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO", "MACOSX_DEPLOYMENT_TARGET=11.0",
        "CODE_SIGNING_ALLOWED=NO",
        "CONFIGURATION_BUILD_DIR=" + str(pathlib.Path.cwd() / "test/Plugins"), "build"]
    for relative in (
        "MacOS/COM4D", "Info.plist", "Resources/English.lproj/InfoPlist.strings",
        "constants.xlf", "manifest.json", "_CodeSignature/CodeResources"):
        assert not (contents / relative).exists(), relative
    if not os.environ.get("STALE_BUILD"):
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "MacOS/COM4D").write_bytes(b"fresh-macos")
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleShortVersionString": os.environ["SOURCE_VERSION"],
            "CFBundleExecutable": "COM4D", "CFBundleIdentifier": "com.4D.COM4Dv3",
            "CFBundlePackageType": "BNDL",
        }, fmt=plistlib.FMT_BINARY))
        (contents / "Resources/English.lproj").mkdir(parents=True, exist_ok=True)
        localized = {
            "CFBundleName": "COM4D", "CFBundleShortVersionString": os.environ["SOURCE_VERSION"],
            "CFBundleGetInfoString": "COM4D version " + os.environ["SOURCE_VERSION"] +
                                   ", Copyright 2020 miyako.",
        }
        target = contents / "Resources/English.lproj/InfoPlist.strings"
        target.write_bytes(plistlib.dumps(localized, fmt=plistlib.FMT_BINARY))
        for name in ("manifest.json", "constants.xlf"):
            shutil.copyfile(name, contents / name)
        db = pathlib.Path("build/XCBuildData")
        db.mkdir(parents=True, exist_ok=True)
        for name in ("build.db", "build.db-wal", "build.db-shm"):
            (db / name).write_bytes(b"fresh-database")
elif tool == "lipo":
    assert args == ["-archs", "test/Plugins/COM4D.bundle/Contents/MacOS/COM4D"]
    print(os.environ.get("ARCHES", "arm64 x86_64"))
elif tool == "base64":
    assert args[:2] == ["--decode", "-o"]
    pathlib.Path(args[2]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "security":
    if args[0] == "find-identity":
        print("" if os.environ.get("MISSING_IDENTITY") else
              '  1) OFFLINE "Developer ID Application: Fixture"')
elif tool == "codesign":
    if "--verify" in args:
        assert "--deep" in args and "--strict" in args
        if os.environ.get("FAIL_VERIFY"):
            sys.exit(7)
    else:
        assert "--options=runtime" in args and "--timestamp" in args
        (contents / "_CodeSignature").mkdir(exist_ok=True)
        (contents / "_CodeSignature/CodeResources").write_bytes(b"fresh-signature")
elif tool in ("ditto", "hdiutil"):
    suffix = "zip" if tool == "ditto" else "dmg"
    assert args[-1] == "COM4D-" + os.environ["VERSION"] + "." + suffix
    assert "test/Plugins/COM4D.bundle" in args
    if not os.environ.get("MISSING_ARCHIVE"):
        pathlib.Path(args[-1]).write_bytes(b"" if os.environ.get("EMPTY_ARCHIVE")
                                         else b"offline-package")
elif tool == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        assert args[-3:] == ["--wait", "--output-format", "json"]
        response = os.environ.get("NOTARY_JSON")
        print(response if response is not None else json.dumps(
            {"id": "offline-id", "status": os.environ.get("NOTARY_STATUS", "Accepted")}))
        sys.exit(int(os.environ.get("NOTARY_EXIT", "0")))
    elif args[:2] == ["stapler", "staple"]:
        sys.exit(int(os.environ.get("STAPLE_EXIT", "0")))
    else:
        assert args[:2] == ["notarytool", "store-credentials"], args
else:
    sys.exit("Unexpected native tool: " + tool)
'''


class NativeShellTests(Fixture):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.sources(self.checkout)
        shutil.copytree(ROOT / ".github/scripts", self.checkout / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("manifest.json", "constants.xlf"):
            target = self.checkout / name
            target.write_bytes(original(name))
        self.tools = self.root / "tools"
        self.tools.mkdir()
        for tool in ("xcodebuild", "lipo", "base64", "security", "codesign",
                     "ditto", "hdiutil", "xcrun"):
            path = self.tools / tool
            path.write_text(STUB.replace("PYTHON", sys.executable))
            path.chmod(0o755)
        (self.tools / "python3").symlink_to(sys.executable)
        for tool in ("grep", "head", "sed"):
            (self.tools / tool).symlink_to(shutil.which(tool))
        self.version = source.read(self.checkout)
        self.log = self.root / "native.jsonl"
        self.env = {
            "PATH": str(self.tools), "HOME": str(self.checkout), "LC_ALL": "C",
            "RUNNER_TEMP": str(self.checkout), "NATIVE_LOG": str(self.log),
            "PRODUCT_NAME": "COM4D", "BASE_DIR": "test", "MACOS_DEPLOYMENT_TARGET": "11.0",
            "VERSION": self.version, "SOURCE_VERSION": self.version,
            "KEYCHAIN_PATH": str(self.checkout / "offline.keychain"),
            "GITHUB_ENV": str(self.checkout / "github-env"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CERT_BASE64": "b2ZmbGluZQ==", "CERT_PASSWORD": "offline-only",
            "KEYCHAIN_PASSWORD": "offline-only", "APPLE_ID": "offline@example.invalid",
            "TEAM_ID": "OFFLINEONLY", "APP_PASSWORD": "offline-only",
        }
        self.contents = self.checkout / native.BUNDLE / "Contents"
        self.protected = {}
        for path in (
            native.BUNDLE / "Contents/Windows/COM4D.4DX",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            native.BUNDLE / "Contents/Resources/constants.xlf",
            "test/Plugins/Default/COM4D.bundle/Contents/Info.plist",
            "test/Plugins/Default/keep", "build/unrelated/keep", "a/libjsoncpp.a",
        ):
            target = self.checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"preserved original bytes")
            self.protected[target] = target.read_bytes()
        for path in native.FILES:
            target = self.checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"stale tracked generated bytes")
        download = self.checkout / native.DOWNLOAD
        download.parent.mkdir()
        download.write_bytes(b"downloaded-windows")

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def phase(self, phase, success=True):
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", ".github/scripts/native.sh", phase],
            cwd=self.checkout, env=self.env, text=True, capture_output=True, timeout=30)
        if success is True:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        elif success is False:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        if result.returncode == 0:
            emitted = self.checkout / "github-env"
            if emitted.exists():
                for line in emitted.read_text().splitlines():
                    key, value = line.split("=", 1)
                    self.env[key] = value
        return result

    def pipeline(self):
        for phase in ("import-certificate", "store-credentials", "build", "verify",
                      "merge-windows", "sign", "package"):
            result = self.phase(phase, success=None)
            if result.returncode:
                return result
        return result

    def reset_assets(self):
        for suffix in ("zip", "dmg"):
            (self.checkout / f"COM4D-{self.env['VERSION']}.{suffix}").unlink(missing_ok=True)

    def build_merge(self):
        self.phase("build")
        self.phase("verify")
        self.assertFalse((self.checkout / native.SIGNATURE).exists())
        self.phase("merge-windows")

    def test_complete_real_shell_pipeline_preserves_inputs_and_generated_bytes(self):
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = {
            "MacOS/COM4D": b"fresh-macos", "Windows64/COM4D.4DX": b"downloaded-windows",
            "_CodeSignature/CodeResources": b"fresh-signature",
        }
        for path, data in expected.items():
            self.assertEqual((self.contents / path).read_bytes(), data)
        for path, data in self.protected.items():
            self.assertEqual(path.read_bytes(), data)
        for name in ("constants.xlf", "manifest.json"):
            self.assertEqual((self.contents / name).read_bytes(), original(name))
        for name in ("build.db", "build.db-wal", "build.db-shm"):
            self.assertEqual((self.checkout / "build/XCBuildData" / name).read_bytes(), b"fresh-database")
        calls = self.calls()
        index = lambda test: next(i for i, call in enumerate(calls) if test(call))
        sign = index(lambda call: call[0] == "codesign")
        package = index(lambda call: call[0] == "ditto")
        staple = index(lambda call: call[:3] == ["xcrun", "stapler", "staple"])
        self.assertLess(index(lambda call: call[0] == "xcodebuild"), sign)
        self.assertLess(sign, package)
        self.assertLess(package, staple)
        self.assertTrue(any(i > staple and call[0] == "codesign" and "--verify" in call
                            for i, call in enumerate(calls)))
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"] for call in calls), 2)
        environment = (self.checkout / "github-env").read_text()
        self.assertIn(f"ZIP_PATH=COM4D-{self.version}.zip\n", environment)
        self.assertIn(f"DMG_PATH=COM4D-{self.version}.dmg\n", environment)

    def test_unsigned_verification_and_merge_do_not_require_signature(self):
        self.build_merge()
        with cwd(self.checkout):
            native.validate_outputs(signed=False)
            with self.assertRaises(ValueError):
                native.validate_outputs()
        self.phase("sign")
        with cwd(self.checkout):
            native.validate_outputs()

    def test_pipeline_uses_live_selected_version_and_compiled_localization(self):
        version = "3.2.1"
        for path in source.SOURCE_PATHS:
            target = self.checkout / path
            target.write_bytes(target.read_bytes().replace(self.version.encode(), version.encode()))
        self.env.update(SOURCE_VERSION=version, VERSION=version)
        self.assertEqual(source.read(self.checkout), version)
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(plistlib.loads((self.contents / "Info.plist").read_bytes())[
            "CFBundleShortVersionString"], version)
        self.assertEqual(plistlib.loads((self.contents / "Resources/English.lproj/InfoPlist.strings"
                                        ).read_bytes())["CFBundleShortVersionString"], version)
        self.assertTrue((self.checkout / f"COM4D-{version}.zip").is_file())

    def test_xml_built_metadata_and_source_utf16_localization_are_supported(self):
        self.phase("build")
        plist = self.contents / "Info.plist"
        plist.write_bytes(plistlib.dumps(plistlib.loads(plist.read_bytes()),
                                         fmt=plistlib.FMT_XML))
        localized = self.contents / "Resources/English.lproj/InfoPlist.strings"
        localized.write_bytes((self.checkout / source.LOCALIZED).read_text().encode("utf-16"))
        self.phase("verify")
        compiled = {
            "CFBundleShortVersionString": self.version,
            "CFBundleGetInfoString": f"COM4D version {self.version}, Copyright 2020 miyako.",
        }
        localized.write_bytes(plistlib.dumps(compiled, fmt=plistlib.FMT_XML))
        self.phase("verify")

    def test_missing_stale_empty_binary_and_exact_architecture_tokens(self):
        self.env["STALE_BUILD"] = "1"
        self.phase("build")
        self.phase("verify", success=False)
        self.env.pop("STALE_BUILD")
        self.phase("build")
        binary = self.contents / "MacOS/COM4D"
        binary.write_bytes(b"")
        self.phase("verify", success=False)
        binary.write_bytes(b"fresh")
        for arches in ("arm64e x86_64", "arm64 x86_64h", "", "i386"):
            self.env["ARCHES"] = arches
            self.phase("verify", success=False)
        self.env["ARCHES"] = "arm64 x86_64 arm64e i386"
        self.phase("verify")
        self.env["FAIL_TOOL"] = "lipo"
        self.phase("verify", success=False)

    def test_metadata_localization_and_resource_drift_fail_unsigned_validation(self):
        self.phase("build")
        for relative in ("Info.plist", "Resources/English.lproj/InfoPlist.strings",
                         "constants.xlf", "manifest.json"):
            path = self.contents / relative
            saved = path.read_bytes()
            for data in (None, b"", b"drift"):
                with self.subTest(relative=relative, data=data):
                    if data is None:
                        path.unlink()
                    else:
                        path.write_bytes(data)
                    self.phase("verify", success=False)
                    path.write_bytes(saved)

    def test_every_final_packaged_leaf_revalidated_before_any_package_tool(self):
        self.build_merge()
        self.phase("sign")
        external = self.checkout / "same-bytes"
        for relative in native.FILES:
            path = self.checkout / relative
            saved = path.read_bytes()
            for change in ("missing", "empty", "directory", "symlink"):
                with self.subTest(relative=relative, change=change):
                    self.log.unlink(missing_ok=True)
                    path.unlink()
                    if change == "empty":
                        path.write_bytes(b"")
                    elif change == "directory":
                        path.mkdir()
                    elif change == "symlink":
                        external.write_bytes(saved)
                        path.symlink_to(external)
                    self.phase("package", success=False)
                    self.assertFalse(any(call[0] in ("ditto", "hdiutil", "xcrun")
                                         for call in self.calls()))
                    if path.is_dir() and not path.is_symlink():
                        path.rmdir()
                    else:
                        path.unlink(missing_ok=True)
                    path.write_bytes(saved)
        self.phase("package")
        for relative in native.FILES:
            self.assertTrue((self.checkout / relative).is_file())

    def test_package_output_safety_before_archive_creation(self):
        self.build_merge()
        self.phase("sign")
        target = self.checkout / f"COM4D-{self.version}.dmg"
        for kind in ("file", "directory", "symlink"):
            self.log.unlink(missing_ok=True)
            if kind == "file":
                target.write_bytes(b"existing")
            elif kind == "directory":
                target.mkdir()
            else:
                target.symlink_to(self.checkout / "missing")
            self.phase("package", success=False)
            self.assertFalse(any(call[0] in ("ditto", "hdiutil") for call in self.calls()))
            if kind == "directory":
                target.rmdir()
            else:
                target.unlink()
        self.env["VERSION"] = "../escape"
        self.phase("package", success=False)
        self.assertFalse((self.root / "escape.zip").exists())

    def test_all_native_credential_and_strict_sign_failures_are_fatal(self):
        for tool, phase in (
            ("base64", "import-certificate"), ("security", "import-certificate"),
            ("xcrun", "store-credentials"), ("xcodebuild", "build"),
        ):
            with self.subTest(tool=tool):
                self.env["FAIL_TOOL"] = tool
                self.phase(phase, success=False)
        self.env.pop("FAIL_TOOL")
        self.build_merge()
        for extra in (
            {"MISSING_IDENTITY": "1"}, {"FAIL_TOOL": "security"},
            {"FAIL_TOOL": "codesign"}, {"FAIL_VERIFY": "1"},
        ):
            with self.subTest(extra=extra):
                saved = dict(self.env)
                self.env.update(extra)
                self.phase("sign", success=False)
                self.env = saved
        self.phase("sign")

    def test_notary_exit_json_schema_duplicates_nonfinite_and_staple_fail_closed(self):
        self.build_merge()
        self.phase("sign")
        cases = [
            {"FAIL_TOOL": tool} for tool in ("ditto", "hdiutil", "xcrun")
        ] + [
            {"NOTARY_EXIT": "5", "NOTARY_STATUS": "Accepted"},
            {"NOTARY_STATUS": "Invalid"}, {"NOTARY_STATUS": ""},
            {"NOTARY_JSON": "not json"}, {"NOTARY_JSON": "[]"},
            {"NOTARY_JSON": "{}"}, {"NOTARY_JSON": '{"status":true}'},
            {"NOTARY_JSON": '{"status":"Invalid","status":"Accepted"}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":{"id":1,"id":2}}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":NaN}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":-Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":1e999}'},
            {"MISSING_ARCHIVE": "1"}, {"EMPTY_ARCHIVE": "1"},
            {"STAPLE_EXIT": "8"}, {"FAIL_VERIFY": "1"},
        ]
        baseline = dict(self.env)
        for extra in cases:
            with self.subTest(extra=extra):
                self.reset_assets()
                self.log.unlink(missing_ok=True)
                self.env = {**baseline, **extra}
                self.phase("package", success=False)
                if "STAPLE_EXIT" not in extra and "FAIL_VERIFY" not in extra:
                    self.assertFalse(any(call[:3] == ["xcrun", "stapler", "staple"]
                                         for call in self.calls()))
        self.env = baseline
        self.reset_assets()
        self.phase("package")

    def test_cleanup_prevalidation_failure_never_invokes_xcode(self):
        first = self.checkout / native.FILES[0]
        signature = self.checkout / native.SIGNATURE
        signature.unlink()
        signature.symlink_to(first)
        self.phase("build", success=False)
        self.assertEqual(first.read_bytes(), b"stale tracked generated bytes")
        self.assertFalse(any(call[0] == "xcodebuild" for call in self.calls()))

    def test_actual_default_project_phase_does_not_invoke_legacy_notarization(self):
        project = (ROOT / source.PROJECT).read_text()
        literal = re.search(r'shellScript = ("(?:\\.|[^"\\])*");', project)[1]
        original_literal = re.search(
            rb'shellScript = ("(?:\\.|[^"\\])*");', original(source.PROJECT))[1]
        self.assertEqual(json.loads(literal), json.loads(original_literal))
        result = subprocess.run(
            ["/bin/sh", "-eu", "-c", json.loads(literal)], cwd=self.checkout,
            env={**self.env, "CONFIGURATION": "Default"}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No notarization performed", result.stdout)
        self.assertEqual(self.calls(), [])

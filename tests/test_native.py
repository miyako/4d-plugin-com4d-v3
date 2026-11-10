"""Narrow cleanup, exact Windows merge, and native leaf safety."""

import os
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
from unittest import mock

from version_support import Fixture, GitFixture, ROOT, cwd
import native


class NativePreparationTests(Fixture):
    def test_selective_cleanup_preserves_every_packaged_and_intermediate_sibling(self):
        protected = (
            native.WINDOWS,
            native.BUNDLE / "Contents/Windows/COM4D.4DX",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            native.BUNDLE / "Contents/Resources/constants.xlf",
            native.BUNDLE / "Contents/Resources/custom.txt",
            "test/Plugins/Default/COM4D.bundle/Contents/Info.plist",
            "test/Plugins/Default/keep", "test/Plugins/Other.bundle/keep",
            "build/unrelated/keep", "build/COM4D.build-evil/keep",
            "a/libjsoncpp.a", "lib/windows64/jsoncpp.lib",
            "build/XCBuildData/build.db",
            "build/XCBuildData/unexpected-source.cpp",
        )
        for path in protected:
            self.write(path, b"preserved exact bytes")
        for path in native.FILES:
            if path != native.WINDOWS:
                self.write(path, b"stale")
        for path in native.DIRECTORIES:
            self.write(path / "intermediate", b"stale")
        with cwd(self.root):
            native.prepare()
            native.prepare()
        for path in protected:
            self.assertEqual((self.root / path).read_bytes(), b"preserved exact bytes", path)
        for path in (*native.DIRECTORIES, *(p for p in native.FILES if p != native.WINDOWS)):
            self.assertFalse((self.root / path).exists(), path)

    def test_windows_cleanup_exact_release_x64_outputs_and_siblings(self):
        files = tuple(native.WINDOWS.with_suffix(suffix) for suffix in
                      (".4DX", ".exp", ".lib", ".pdb"))
        protected = (
            native.BUNDLE / "Contents/Windows/COM4D.4DX",
            native.BUNDLE / "Contents/Windows64/other.dll",
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            "Objs/Debug/keep", "Objs/Release-evil/keep",
        )
        for path in protected:
            self.write(path, b"preserved")
        for path in (*files, Path("Objs/Release/main.obj")):
            self.write(path, b"stale")
        with cwd(self.root):
            native.prepare_windows()
            native.prepare_windows()
        for path in protected:
            self.assertEqual((self.root / path).read_bytes(), b"preserved")
        for path in (*files, Path("Objs/Release")):
            self.assertFalse((self.root / path).exists())

    def test_every_leaf_and_intermediate_prevalidated_before_any_delete(self):
        candidates = (
            native.FILES[-1], native.WINDOWS, native.BUNDLE, native.DIRECTORIES[-1],
            native.DIRECTORIES[0] / "nested/link", native.XCODE_DATA / "nested/link",
        )
        for where in candidates:
            with self.subTest(where=where):
                first = self.write(native.FILES[0], b"must remain")
                external = self.write("outside/keep", b"untouched")
                link = self.root / where
                if link.is_dir():
                    shutil.rmtree(link)
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(external)
                with cwd(self.root), self.assertRaisesRegex(ValueError, "symlink"):
                    native.prepare()
                if where != native.BUNDLE:
                    self.assertEqual(first.read_bytes(), b"must remain")
                self.assertEqual(external.read_bytes(), b"untouched")
                link.unlink()

    def test_wrong_leaf_and_intermediate_types_prevalidated(self):
        for where in (native.FILES[-1], native.DIRECTORIES[-1]):
            first = self.write(native.FILES[0], b"must remain")
            path = self.root / where
            path.parent.mkdir(parents=True, exist_ok=True)
            if where in native.FILES:
                path.mkdir()
            else:
                path.write_bytes(b"not directory")
            with cwd(self.root), self.assertRaises(ValueError):
                native.prepare()
            self.assertEqual(first.read_bytes(), b"must remain")
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()

    def test_windows_reparse_ancestor_is_rejected_before_deletion(self):
        first = self.write(native.WINDOWS, b"must remain")
        self.write("Objs/Release/main.obj", b"must remain")
        real = Path.lstat

        def reparse(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if path == Path("Objs/Release"):
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return result

        with cwd(self.root), mock.patch.object(Path, "lstat", new=reparse):
            with self.assertRaisesRegex(ValueError, "reparse"):
                native.prepare_windows()
        self.assertEqual(first.read_bytes(), b"must remain")
        self.assertEqual((self.root / "Objs/Release/main.obj").read_bytes(), b"must remain")

    def test_windows_symlink_last_leaf_precedes_first_deletion(self):
        first = self.write(native.WINDOWS, b"must remain")
        external = self.write("outside/keep", b"untouched")
        link = self.root / native.WINDOWS.with_suffix(".pdb")
        link.symlink_to(external)
        with cwd(self.root), self.assertRaisesRegex(ValueError, "symlink"):
            native.prepare_windows()
        self.assertEqual(first.read_bytes(), b"must remain")
        self.assertEqual(external.read_bytes(), b"untouched")

    def test_cleanup_io_error_is_fatal(self):
        self.write(native.FILES[0], b"stale")
        with cwd(self.root), mock.patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.prepare()
        self.write(native.DIRECTORIES[0] / "stale", b"stale")
        with cwd(self.root), mock.patch("shutil.rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.prepare()

    def test_resources_are_exact_contents_copies_not_stale_resources_copies(self):
        for name in ("constants.xlf", "manifest.json"):
            self.write(name, b"exact source")
            self.write(native.BUNDLE / "Contents" / name, b"exact source")
        stale = self.write(native.BUNDLE / "Contents/Resources/constants.xlf", b"stale prebuilt")
        with cwd(self.root):
            native.verify_resources()
            for name in ("constants.xlf", "manifest.json"):
                target = native.BUNDLE / "Contents" / name
                target.write_bytes(b"drift")
                with self.assertRaisesRegex(ValueError, "differs"):
                    native.verify_resources()
                target.write_bytes(b"exact source")
        self.assertEqual(stale.read_bytes(), b"stale prebuilt")

    def test_exact_windows_merge_and_late_byte_comparison(self):
        self.write(native.DOWNLOAD, b"fresh downloaded")
        self.write(native.WINDOWS, b"old tracked")
        with cwd(self.root):
            native.merge_windows()
            native.verify_windows()
            self.assertEqual(native.WINDOWS.read_bytes(), b"fresh downloaded")
            native.WINDOWS.write_bytes(b"late substitution")
            with self.assertRaisesRegex(ValueError, "differs"):
                native.verify_windows()

    def test_download_is_exact_sole_nonempty_regular_file_before_merge(self):
        self.write(native.DOWNLOAD, b"fresh")
        target = self.write(native.WINDOWS, b"must remain")
        for extra in ("winbuild/extra.txt", "winbuild/nested/COM4D.4DX"):
            path = self.write(extra, b"unexpected")
            with cwd(self.root), self.assertRaisesRegex(ValueError, "sole"):
                native.merge_windows()
            self.assertEqual(target.read_bytes(), b"must remain")
            path.unlink()
            if path.parent.name == "nested":
                path.parent.rmdir()
        download = self.root / native.DOWNLOAD
        download.unlink()
        with cwd(self.root), self.assertRaises(ValueError):
            native.merge_windows()
        download.write_bytes(b"")
        with cwd(self.root), self.assertRaises(ValueError):
            native.merge_windows()
        download.unlink()
        download.symlink_to(target)
        with cwd(self.root), self.assertRaisesRegex(ValueError, "symlink"):
            native.merge_windows()
        self.assertEqual(target.read_bytes(), b"must remain")

    def test_windows_destination_directory_or_samebytes_symlink_rejected_before_copy(self):
        source = self.write(native.DOWNLOAD, b"fresh")
        target = self.root / native.WINDOWS
        target.parent.mkdir(parents=True)
        target.mkdir()
        with cwd(self.root), self.assertRaises(ValueError):
            native.merge_windows()
        target.rmdir()
        external = self.write("outside/keep", b"fresh")
        target.symlink_to(external)
        with cwd(self.root), self.assertRaisesRegex(ValueError, "symlink"):
            native.merge_windows()
        self.assertEqual(source.read_bytes(), b"fresh")
        self.assertEqual(external.read_bytes(), b"fresh")

    def test_all_packaged_leaves_require_regular_nonempty_nonsymlink(self):
        for relative in native.FILES:
            path = self.write(relative, b"fresh tracked generated bytes")
            with cwd(self.root):
                native.require_file(relative)
                path.unlink()
                with self.assertRaises(ValueError):
                    native.require_file(relative)
                path.write_bytes(b"")
                with self.assertRaises(ValueError):
                    native.require_file(relative)
                path.unlink()
                path.mkdir()
                with self.assertRaises(ValueError):
                    native.require_file(relative)
                path.rmdir()
                external = self.write("samebytes", b"fresh tracked generated bytes")
                path.symlink_to(external)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    native.require_file(relative)
                path.unlink()
                path.write_bytes(b"fresh tracked generated bytes")
                native.require_file(relative)

    def test_output_path_traversal_absolute_symlink_and_fifo_rejected(self):
        with cwd(self.root):
            for path in ("../escape", "/absolute", "build/../escape", "build\\escape"):
                with self.assertRaises(ValueError):
                    native.validate_paths((Path(path),))
            os.mkfifo("fifo")
            with self.assertRaisesRegex(ValueError, "type"):
                native.validate_paths((Path("fifo"),))
            with self.assertRaises(ValueError):
                native.package_paths("../1.2.3")
            self.assertEqual(native.package_paths("1.2.3"),
                             (Path("COM4D-1.2.3.zip"), Path("COM4D-1.2.3.dmg")))
            Path("COM4D-1.2.3.dmg").symlink_to("missing")
            with self.assertRaisesRegex(ValueError, "symlink"):
                native.package_paths("1.2.3")

    def test_generated_classifier_is_exact_and_no_dependency_exceptions(self):
        positives = (
            *map(str, native.FILES), str(native.DOWNLOAD),
            "build/XCBuildData/build.db", "build/XCBuildData/build.db-wal",
            "build/XCBuildData/build.db-shm",
            "build/XCBuildData/0123456789abcdef0123456789abcdef.xcbuilddata/request.json",
            *(str(path / "Objects-normal/arm64/main.o") for path in native.DIRECTORIES),
        )
        for path in positives:
            self.assertTrue(native.generated(path), path)
        for path in (
            "Info.plist", "constants.xlf", "manifest.json", "a/libjsoncpp.a",
            "test/Plugins/COM4D.bundle/Contents/Resources/constants.xlf",
            "test/Plugins/COM4D.bundle/Contents/Windows/COM4D.4DX",
            "test/Plugins/COM4D.bundle/Contents/QuickLook/Thumbnail.png",
            "test/Plugins/Default/COM4D.bundle/Contents/Info.plist",
            "build/XCBuildData-evil/build.db", "build/XCBuildData/build.db-evil",
            "build/XCBuildData/unexpected-source.cpp",
            "build/XCBuildData/evil.xcbuilddata/request.json",
            "build/XCBuildData/0123456789ABCDEF0123456789ABCDEF.xcbuilddata/request.json",
            "build/COM4D.build-evil/input.cpp", "build/unexpected.cpp",
            "Objs/Release/main.obj", "winbuild/nested/COM4D.4DX",
            "../build/COM4D.build/main.o", "/build/COM4D.build/main.o",
            "build\\COM4D.build\\main.o", "build/COM4D.build/../input.cpp",
        ):
            self.assertFalse(native.generated(path), path)


class NativeWindowsCLI(GitFixture):
    def setUp(self):
        super().setUp()
        shutil.copyfile(ROOT / ".github/scripts/native.py",
                        self.local / ".github/scripts/native.py")
        for path in (native.WINDOWS, native.BUNDLE / "Contents/Windows/COM4D.4DX"):
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"tracked original native bytes")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "tracked native inputs")
        self.sha = self.git("rev-parse", "HEAD")

    def verify(self, success=True):
        result = self.cli(".github/scripts/native.py", "verify-built-windows",
                          "--sha", self.sha)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_exact_native_windows_outputs_retained_without_reset(self):
        for suffix in (".4DX", ".exp", ".lib", ".pdb"):
            path = self.local / native.WINDOWS.with_suffix(suffix)
            path.write_bytes(b"fresh native output")
        path = self.local / "Objs/Release/main.obj"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fresh intermediate")
        self.verify()
        self.assertEqual((self.local / native.WINDOWS).read_bytes(), b"fresh native output")
        self.assertEqual((self.local / native.BUNDLE / "Contents/Windows/COM4D.4DX").read_bytes(),
                         b"tracked original native bytes")

    def test_exact_windows_output_required_missing_empty_directory_samebytes_symlink(self):
        path = self.local / native.WINDOWS
        path.unlink()
        self.verify(success=False)
        path.write_bytes(b"")
        self.verify(success=False)
        path.unlink()
        path.mkdir()
        self.verify(success=False)
        path.rmdir()
        path.symlink_to(self.local / native.BUNDLE / "Contents/Windows/COM4D.4DX")
        self.verify(success=False)

    def test_no_recursive_first_match_and_no_intermediate_sibling_allowance(self):
        for relative in (
            "Objs/Release-evil/main.obj", "Objs/Debug/main.obj",
            "test/plugins/Default/COM4D.4DX", "winbuild/nested/COM4D.4DX",
            "test/Plugins/COM4D.bundle/Contents/Windows64/other.dll",
        ):
            target = self.local / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"unexpected")
            self.verify(success=False)
            target.unlink()

    def test_native_windows_staged_output_and_source_changes_never_exempt(self):
        path = self.local / native.WINDOWS
        path.write_bytes(b"fresh output")
        self.git("add", str(native.WINDOWS))
        self.verify(success=False)
        self.git("reset", "--quiet", "HEAD", "--", str(native.WINDOWS))
        source = self.local / "COM4D.xcodeproj/project.pbxproj"
        source.write_bytes(source.read_bytes() + b"\n// changed source")
        self.verify(success=False)

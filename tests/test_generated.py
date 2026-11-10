"""Only native-proven generated families may differ at publication."""

import unittest

from helper_support import source
import native


class GeneratedOutputTests(unittest.TestCase):
    def test_exact_native_paths_and_xcode_intermediates(self):
        paths = (
            *map(str, native.FILES), str(native.WINDOWS), "winbuild/COM4D.4DX",
            "build/XCBuildData/build.db", "build/XCBuildData/build.db-wal",
            "build/XCBuildData/build.db-shm",
            "build/XCBuildData/0123456789abcdef0123456789abcdef.xcbuilddata/request.json",
            *(str(path / "Objects-normal/arm64/main.o") for path in native.DIRECTORIES),
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(native.generated(path))

    def test_sources_prebuilt_siblings_and_unproven_outputs_are_immutable(self):
        paths = (
            *map(str, source.SOURCE_PATHS),
            "test/Plugins/COM4D.bundle/Contents/Windows/COM4D.4DX",
            "test/Plugins/COM4D.bundle/Contents/QuickLook/Thumbnail.png",
            "test/Plugins/COM4D.bundle/Contents/Resources/constants.xlf",
            "test/Plugins/COM4D.bundle/Contents/MacOS/runtime.dylib",
            "test/Plugins/Default/COM4D.bundle/Contents/Info.plist",
            "test/Plugins/COM4D.bundle/Contents/_CodeSignature-evil/file",
            "build/COM4D.build-evil/input.cpp", "build/XCBuildData-evil/build.db",
            "build/unexpected-source.cpp", "build/XCBuildData/unexpected-source.cpp",
            "build/XCBuildData/build.db-evil",
            "build/XCBuildData/evil.xcbuilddata/request.json",
            "build/XCBuildData/0123456789ABCDEF0123456789ABCDEF.xcbuilddata/request.json",
            "../build/COM4D.build/file.o", "/build/COM4D.build/file.o",
            "build\\COM4D.build\\file.o", "winbuild/other.4DX",
            "a/libapr-1.a", "jsoncpp-build/lib/libjsoncpp.a",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(native.generated(path))

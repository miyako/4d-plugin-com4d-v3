"""Rebuild only COM4D's proven generated leaves; preserve packaged siblings."""

import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import stat

from repository import is_link


PRODUCT = "COM4D"
BASE = Path("test/Plugins")
BUNDLE = BASE / f"{PRODUCT}.bundle"
WINDOWS = BUNDLE / f"Contents/Windows64/{PRODUCT}.4DX"
DOWNLOAD = Path(f"winbuild/{PRODUCT}.4DX")
FILES = tuple(BUNDLE / relative for relative in (
    f"Contents/MacOS/{PRODUCT}", "Contents/Info.plist",
    "Contents/Resources/English.lproj/InfoPlist.strings",
    "Contents/constants.xlf", "Contents/manifest.json",
    f"Contents/Windows64/{PRODUCT}.4DX",
    "Contents/_CodeSignature/CodeResources",
))
SIGNATURE = FILES[-1]
XCODE_DATA = Path("build/XCBuildData")
DIRECTORIES = (
    Path(f"build/{PRODUCT}.build"),
    Path(f"build/Default/{PRODUCT}.build"),
    BASE / f"{PRODUCT}.build",
)


def generated(path):
    if not isinstance(path, str) or "\\" in path:
        return False
    relative = PurePosixPath(path)
    if relative.is_absolute() or relative.as_posix() != path or ".." in relative.parts:
        return False
    return (
        path in set(map(str, (*FILES, DOWNLOAD)))
        or bool(re.fullmatch(
            r"build/XCBuildData/(?:build\.db(?:-wal|-shm)?|"
            r"[0-9a-f]{32}\.xcbuilddata/.+)", path))
        or any(path.startswith(str(directory) + "/") for directory in DIRECTORIES)
    )


def validate_paths(paths):
    root = Path.cwd().resolve()
    for value in paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or "\\" in str(path):
            raise ValueError(f"Output escapes checkout: {path}")
        for parent in (*reversed(path.parents), path):
            if parent == Path("."):
                continue
            if is_link(parent):
                raise ValueError(f"Refusing symlink/reparse output: {parent}")
            try:
                mode = parent.lstat().st_mode
            except FileNotFoundError:
                continue
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f"Unsupported output type: {parent}")
            if parent != path and not stat.S_ISDIR(mode):
                raise ValueError(f"Output ancestor is not a directory: {parent}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Output escapes checkout: {path}")
        if path.is_dir():
            for descendant in path.rglob("*"):
                if is_link(descendant):
                    raise ValueError(f"Refusing symlink/reparse output: {descendant}")
                mode = descendant.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError(f"Unsupported output type: {descendant}")


def clean(files, directories):
    validate_paths((*files, *directories, XCODE_DATA))
    for path in files:
        if path.exists() and not path.is_file():
            raise ValueError(f"Generated leaf is not a regular file: {path}")
    for path in directories:
        if path.exists() and not path.is_dir():
            raise ValueError(f"Intermediate root is not a directory: {path}")
    for path in files:
        path.unlink(missing_ok=True)
    for path in directories:
        if path.exists():
            shutil.rmtree(path)


def prepare():
    validate_paths((WINDOWS,))
    clean(tuple(path for path in FILES if path != WINDOWS), DIRECTORIES)


def prepare_windows():
    files = tuple(WINDOWS.with_suffix(suffix) for suffix in (".4DX", ".exp", ".lib", ".pdb"))
    clean(files, (Path("Objs/Release"),))


def verify_built_windows(sha):
    files = tuple(WINDOWS.with_suffix(suffix) for suffix in (".4DX", ".exp", ".lib", ".pdb"))
    validate_paths((*files, Path("Objs/Release")))
    require_file(WINDOWS)
    from repository import verify_checkout
    verify_checkout(
        sha, final=True,
        generated=lambda path: path in set(map(str, files))
        or generated_windows_intermediate(path),
    )


def generated_windows_intermediate(path):
    relative = PurePosixPath(path)
    return (
        "\\" not in path and relative.as_posix() == path
        and not relative.is_absolute() and ".." not in relative.parts
        and path.startswith("Objs/Release/")
    )


def require_file(path):
    path = Path(path)
    validate_paths((path,))
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty native output: {path}")


def verify_resources():
    for name in ("manifest.json", "constants.xlf"):
        copied = BUNDLE / "Contents" / name
        require_file(copied)
        require_file(Path(name))
        if copied.read_bytes() != Path(name).read_bytes():
            raise ValueError(f"Copied resource differs from exact source: {copied}")


def validate_windows():
    validate_paths((WINDOWS, Path("winbuild")))
    if not Path("winbuild").is_dir() or set(Path("winbuild").iterdir()) != {DOWNLOAD}:
        raise ValueError("Expected sole downloaded winbuild/COM4D.4DX artifact")
    require_file(DOWNLOAD)
    if WINDOWS.exists() and not WINDOWS.is_file():
        raise ValueError(f"Windows destination is not a regular file: {WINDOWS}")


def merge_windows():
    validate_windows()
    WINDOWS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DOWNLOAD, WINDOWS)
    verify_windows()


def verify_windows():
    validate_windows()
    require_file(WINDOWS)
    if WINDOWS.read_bytes() != DOWNLOAD.read_bytes():
        raise ValueError("Merged Windows payload differs from downloaded artifact")


def validate_outputs(*, signed=True, windows=True):
    validate_paths((*FILES, *DIRECTORIES, XCODE_DATA))
    for path in FILES:
        if (signed or path != SIGNATURE) and (windows or path != WINDOWS):
            require_file(path)
    from version import verify_bundle
    verify_bundle(BUNDLE)
    verify_resources()
    if windows:
        verify_windows()


def package_paths(version):
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise ValueError("Expected canonical source version")
    paths = tuple(Path(f"{PRODUCT}-{version}.{suffix}") for suffix in ("zip", "dmg"))
    validate_paths(paths)
    if any(path.exists() for path in paths):
        raise ValueError("Package output already exists")
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=(
        "clean-macos", "clean-windows", "verify-resources", "validate-windows",
        "merge-windows", "verify-unsigned", "verify-merged", "verify-final",
        "package-paths", "verify-built-windows",
    ))
    parser.add_argument("version", nargs="?")
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.phase == "clean-macos":
        prepare()
    elif args.phase == "clean-windows":
        prepare_windows()
    elif args.phase == "verify-resources":
        verify_resources()
    elif args.phase == "validate-windows":
        validate_windows()
    elif args.phase == "merge-windows":
        merge_windows()
    elif args.phase == "package-paths":
        package_paths(args.version or "")
    elif args.phase == "verify-built-windows":
        verify_built_windows(args.sha)
    else:
        validate_outputs(signed=args.phase == "verify-final",
                         windows=args.phase != "verify-unsigned")


if __name__ == "__main__":
    main()

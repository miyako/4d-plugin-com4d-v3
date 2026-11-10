#!/bin/bash
set -euo pipefail

test "${PRODUCT_NAME:?}" = COM4D
test "${BASE_DIR:?}" = test
BUNDLE_PATH="test/Plugins/COM4D.bundle"

case "${1:?native phase required}" in
  import-certificate)
    KEYCHAIN_PATH="$RUNNER_TEMP/build.keychain-db"
    CERT_PATH="$RUNNER_TEMP/certificate.p12"
    printf '%s' "$CERT_BASE64" | base64 --decode -o "$CERT_PATH"
    security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security import "$CERT_PATH" -P "$CERT_PASSWORD" -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
    security list-keychain -d user -s "$KEYCHAIN_PATH" login.keychain
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    echo "KEYCHAIN_PATH=$KEYCHAIN_PATH" >> "$GITHUB_ENV"
    ;;
  store-credentials)
    xcrun notarytool store-credentials "notarytool-profile" \
      --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD" \
      --keychain "$KEYCHAIN_PATH"
    ;;
  build)
    python3 .github/scripts/native.py clean-macos
    xcodebuild -project "$PRODUCT_NAME.xcodeproj" \
      -target "$PRODUCT_NAME" \
      -configuration Default \
      ARCHS="arm64 x86_64" \
      ONLY_ACTIVE_ARCH=NO \
      MACOSX_DEPLOYMENT_TARGET="$MACOS_DEPLOYMENT_TARGET" \
      CODE_SIGNING_ALLOWED=NO \
      CONFIGURATION_BUILD_DIR="$PWD/test/Plugins" \
      build
    ;;
  verify)
    python3 .github/scripts/native.py verify-unsigned
    architectures=$(lipo -archs "$BUNDLE_PATH/Contents/MacOS/COM4D")
    read -r -a architecture_tokens <<< "$architectures"
    have_arm64=0
    have_x86_64=0
    for architecture in "${architecture_tokens[@]}"; do
      case "$architecture" in
        arm64) have_arm64=1 ;;
        x86_64) have_x86_64=1 ;;
      esac
    done
    test "$have_arm64" = 1
    test "$have_x86_64" = 1
    ;;
  merge-windows)
    python3 .github/scripts/native.py merge-windows
    python3 .github/scripts/native.py verify-merged
    echo "BUNDLE_PATH=$BUNDLE_PATH" >> "$GITHUB_ENV"
    ;;
  sign)
    python3 .github/scripts/native.py verify-merged
    IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
      | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)".*/\1/')
    test -n "$IDENTITY"
    codesign --verbose --deep --timestamp --force --options=runtime \
      --sign "$IDENTITY" "$BUNDLE_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    python3 .github/scripts/native.py verify-final
    echo "BUNDLE_PATH=$BUNDLE_PATH" >> "$GITHUB_ENV"
    ;;
  package)
    python3 .github/scripts/native.py verify-final
    python3 .github/scripts/native.py package-paths "$VERSION"
    ZIP_PATH="COM4D-${VERSION}.zip"
    DMG_PATH="COM4D-${VERSION}.dmg"
    ditto -c -k --keepParent "$BUNDLE_PATH" "$ZIP_PATH"
    hdiutil create -format UDBZ -volname "$PRODUCT_NAME" -srcfolder "$BUNDLE_PATH" "$DMG_PATH"
    python3 - "$ZIP_PATH" "$DMG_PATH" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".github/scripts")
from native import require_file
for path in sys.argv[1:]:
    require_file(Path(path))
PY
    for artifact in "$ZIP_PATH" "$DMG_PATH"; do
      response=$(xcrun notarytool submit "$artifact" \
        --keychain-profile "notarytool-profile" --keychain "$KEYCHAIN_PATH" \
        --wait --output-format json)
      printf '%s' "$response" | python3 -c \
        'import json,math,sys
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate notarization JSON key: " + key)
        result[key] = value
    return result
def invalid_constant(value):
    raise ValueError("Nonfinite notarization JSON value: " + value)
def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite notarization JSON number: " + value)
    return result
result = json.load(sys.stdin, object_pairs_hook=unique_object,
                   parse_constant=invalid_constant, parse_float=finite_float)
sys.exit(0 if isinstance(result,dict) and result.get("status") == "Accepted" else "Notarization was not Accepted: " + repr(result))'
    done
    xcrun stapler staple "$DMG_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    python3 .github/scripts/native.py verify-final
    python3 - "$ZIP_PATH" "$DMG_PATH" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".github/scripts")
from native import require_file
for path in sys.argv[1:]:
    require_file(Path(path))
PY
    echo "ZIP_PATH=$ZIP_PATH" >> "$GITHUB_ENV"
    echo "DMG_PATH=$DMG_PATH" >> "$GITHUB_ENV"
    ;;
  *)
    echo "Unknown native phase: $1" >&2
    exit 1
    ;;
esac

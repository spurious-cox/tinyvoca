#!/bin/zsh
# Build TinyVoca.app (Apple silicon, Developer ID signed with the hardened runtime) into dist/.
# --install also copies it to /Applications.
# gui.py and setup-engine.sh are bundled in the app; the app builds the Python engine itself on first launch.
set -e
cd "${0:A:h}"
VER=$(sed -n 's/^let appVersion = "\(.*\)"/\1/p' main.swift)
rm -rf dist; mkdir -p dist/TinyVoca.app/Contents/{MacOS,Resources}
# PyTorch no longer ships wheels for Intel Macs, so the app is Apple silicon only.
swiftc -O -swift-version 5 -target arm64-apple-macos12 main.swift -o dist/TinyVoca.app/Contents/MacOS/TinyVoca
cp gui.py setup-engine.sh dist/TinyVoca.app/Contents/Resources/
chmod +x dist/TinyVoca.app/Contents/Resources/setup-engine.sh
ICON=""; for f in AppIcon.icns icon/AppIcon.icns; do [[ -f "$f" ]] && ICON="$f" && break; done
ICONKEY=""
if [[ -n "$ICON" ]]; then cp "$ICON" dist/TinyVoca.app/Contents/Resources/AppIcon.icns; ICONKEY="<key>CFBundleIconFile</key><string>AppIcon</string>"; fi
cat > dist/TinyVoca.app/Contents/Info.plist <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>TinyVoca</string>
<key>CFBundleDisplayName</key><string>TinyVoca</string>
<key>CFBundleIdentifier</key><string>com.timmccoy.tinyvoca</string>
<key>CFBundleExecutable</key><string>TinyVoca</string>
$ICONKEY
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>$VER</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
<key>NSHumanReadableCopyright</key><string>Copyright © 2026 Tim McCoy. tiny-voca is by Muhammed Nazeem (Apache-2.0).</string>
</dict></plist>
PL
SIGN_ID="4208ABA3EC12F24C1F09C7BB624EFF68B44259DB"
codesign --force --deep --timestamp --options runtime --sign "$SIGN_ID" dist/TinyVoca.app
echo "built TinyVoca $VER"
if [[ "$1" == "--install" ]]; then
    pkill -x TinyVoca 2>/dev/null || true
    rm -rf /Applications/TinyVoca.app
    ditto dist/TinyVoca.app /Applications/TinyVoca.app
    echo "installed /Applications/TinyVoca.app"
fi

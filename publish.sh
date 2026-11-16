#!/bin/zsh
# Notarize and staple dist/TinyVoca.app, wrap it in a notarized DMG, and write/refresh the Homebrew cask.
# Run ./build.sh first. Then create the GitHub release (the last line printed shows the command).
#
# Notarization credentials come from a keychain profile created once:
#   xcrun notarytool store-credentials "PixProNotary" --apple-id <appleid> --team-id RUDN8D7ZN9
set -e
cd "${0:A:h}"
NAME="TinyVoca"
APP="dist/$NAME.app"
DEVID="4208ABA3EC12F24C1F09C7BB624EFF68B44259DB"
PROFILE="${NOTARY_PROFILE:-PixProNotary}"
TAP="$(brew --repository)/Library/Taps/spurious-cox/homebrew-tap"
CASK="$TAP/Casks/tinyvoca.rb"
[[ -d "$APP" ]] || { print -u2 "error: build first (./build.sh)"; exit 1; }
VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")
DMG="dist/$NAME-$VERSION.dmg"

print "==> notarizing the app ($NAME $VERSION)"
rm -f dist/app.zip
ditto -c -k --keepParent "$APP" dist/app.zip
xcrun notarytool submit dist/app.zip --keychain-profile "$PROFILE" --wait
rm -f dist/app.zip
xcrun stapler staple "$APP"

print "==> building the disk image"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/READ ME FIRST.txt" <<EOF
$NAME $VERSION

INSTALLING
    Drag $NAME onto the Applications folder beside it.

FIRST LAUNCH
    The first time it opens, TinyVoca sets itself up: it needs Python 3.10 or
    newer (brew install python, or python.org) and an internet connection to
    download PyTorch, tiny-voca and the model weights (about 300 MB, one time).
    It needs a Mac with Apple silicon and macOS 12 or later.

ABOUT TINY-VOCA
    The voice model is tiny-voca by Muhammed Nazeem (Apache-2.0):
    https://github.com/n4ze3m/tiny-voca
    https://huggingface.co/n4ze3m/tiny-voca

HOMEBREW
    brew install --cask spurious-cox/tap/tinyvoca

https://github.com/spurious-cox/tinyvoca

(c) 2026 Tim McCoy
EOF
rm -f "$DMG"
if ! diskutil image create from "$STAGE" --volumeName "$NAME" --format UDZO "$DMG" >/dev/null 2>/tmp/tinyvoca_dmg.err; then
    print "    diskutil failed: $(tr -d '\n' < /tmp/tinyvoca_dmg.err); falling back to hdiutil"
    hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
fi
rm -rf "$STAGE"

print "==> signing and notarizing the disk image"
codesign --force --timestamp --sign "$DEVID" "$DMG"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"
SHA=$(shasum -a 256 "$DMG" | cut -d" " -f1)

print "==> the cask"
if [[ -f "$CASK" ]]; then
    /usr/bin/sed -i "" -e "s/^  version \".*\"/  version \"$VERSION\"/" -e "s/^  sha256 \".*\"/  sha256 \"$SHA\"/" "$CASK"
else
    cat > "$CASK" <<EOF
cask "tinyvoca" do
  version "$VERSION"
  sha256 "$SHA"

  url "https://github.com/spurious-cox/tinyvoca/releases/download/v#{version}/TinyVoca-#{version}.dmg"
  name "TinyVoca"
  desc "Tester for the tiny-voca text-to-speech model and the macOS system voices"
  homepage "https://github.com/spurious-cox/tinyvoca"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: :monterey

  app "TinyVoca.app"

  zap trash: [
    "~/Library/Application Support/TinyVoca",
    "~/Library/Saved Application State/com.timmccoy.tinyvoca.savedState",
  ]

  caveats <<~EOS
    On first launch TinyVoca sets itself up: it needs Python 3.10 or newer
    (brew install python) and an internet connection to download PyTorch,
    tiny-voca and the model weights, about 300 MB, one time.
  EOS
end
EOF
fi
print "    $CASK -> $VERSION"

print "==> results"
print "    dmg:     $DMG ($(du -h "$DMG" | cut -f1))"
print "    stapled: app $(xcrun stapler validate "$APP" >/dev/null 2>&1 && echo YES || echo no), dmg $(xcrun stapler validate "$DMG" >/dev/null 2>&1 && echo YES || echo no)"
print "    sha256:  $SHA"
print "    next:    gh release create v$VERSION \"$DMG\" --repo spurious-cox/tinyvoca --title \"$NAME $VERSION\" --notes ..."

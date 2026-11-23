#!/bin/zsh
# Compile the Icon Composer source on macOS and prepare the generated
# Tauri platform override used only for that build.
set -euo pipefail
here=${0:A:h}
desktop=${here:h}

"$here/make_icon.sh"
cp "$desktop/Resources/AppIcon.icns" "$desktop/src-tauri/icons/icon.icns"

cat > "$desktop/src-tauri/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIconName</key>
  <string>AppIcon</string>
</dict>
</plist>
PLIST

cat > "$desktop/src-tauri/tauri.macos.conf.json" <<'JSON'
{
  "bundle": {
    "resources": {
      "../Resources/Assets.car": "Assets.car"
    },
    "macOS": {
      "infoPlist": "Info.plist"
    }
  }
}
JSON

echo "prepared Liquid Glass macOS icon resources"

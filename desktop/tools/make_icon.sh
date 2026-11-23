#!/bin/zsh
# Compiles desktop/Icon/AppIcon.icon with actool and writes:
#   desktop/Resources/Assets.car
#   desktop/Resources/AppIcon.icns
set -euo pipefail
here=${0:A:h}
desktop=${here:h}
icon="$desktop/Icon/AppIcon.icon"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$desktop/Resources"

xcrun actool "$icon" --compile "$work" --platform macosx \
  --minimum-deployment-target 26.0 --app-icon AppIcon \
  --output-partial-info-plist "$work/partial.plist" \
  --output-format human-readable-text --errors --warnings >"$work/log" 2>&1 || { cat "$work/log"; exit 1; }
[[ -f "$work/Assets.car" && -f "$work/AppIcon.icns" ]] || { cat "$work/log"; echo "actool wrote no icon"; exit 1; }
cp "$work/Assets.car" "$work/AppIcon.icns" "$desktop/Resources/"
echo "wrote Resources/Assets.car and Resources/AppIcon.icns"

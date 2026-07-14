#!/bin/bash
# Builds dist/GitGood.app via py2app, then strips the Qt modules/frameworks/
# plugins we don't use -- py2app's PySide6 recipe bundles the ENTIRE PySide6
# distribution (QtWebEngine, QtQuick/QML, Qt3D, etc: ~1.1GB) regardless of
# what the app actually imports (QtCore/QtGui/QtWidgets only). Trimming this
# takes the bundle from ~1.2GB down to a reasonable size without touching
# anything the app actually loads. Finishes with an ad-hoc codesign, which
# needs to happen AFTER trimming since removing files invalidates the seal.
set -euo pipefail
shopt -s nullglob
cd "$(dirname "$0")"

rm -rf build dist
python setup.py py2app

APP="dist/GitGood.app"
PYSIDE_DIR=$(find "$APP/Contents/Resources/lib" -maxdepth 2 -type d -name "PySide6" | head -1)
if [ -z "$PYSIDE_DIR" ]; then
  echo "Could not locate the bundled PySide6 directory -- aborting trim." >&2
  exit 1
fi
QT_LIB="$PYSIDE_DIR/Qt/lib"
QT_PLUGINS="$PYSIDE_DIR/Qt/plugins"

KEEP_FRAMEWORKS="QtCore QtGui QtWidgets QtDBus"
KEEP_PLUGINS="platforms styles imageformats iconengines generic platforminputcontexts"

for fw in "$QT_LIB"/*.framework; do
  name=$(basename "$fw" .framework)
  case " $KEEP_FRAMEWORKS " in *" $name "*) ;; *) rm -rf "$fw" ;; esac
done

for so in "$PYSIDE_DIR"/Qt*.abi3.so; do
  name=$(basename "$so" .abi3.so)
  case " $KEEP_FRAMEWORKS " in *" $name "*) ;; *) rm -f "$so" ;; esac
done

rm -rf "$PYSIDE_DIR/Qt/qml" "$PYSIDE_DIR/Qt/translations"

for plugin_dir in "$QT_PLUGINS"/*/; do
  name=$(basename "$plugin_dir")
  case " $KEEP_PLUGINS " in *" $name "*) ;; *) rm -rf "$plugin_dir" ;; esac
done

codesign --force --deep -s - "$APP"

echo "Final size:"
du -sh "$APP"

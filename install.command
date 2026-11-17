#!/bin/bash
# ChATlas installer for macOS (Miniconda / Miniforge / Anaconda)
set -e
cd "$(dirname "$0")"
echo ""
echo "   ============================================="
echo "     ChATlas  -  retina connectome explorer"
echo "   ============================================="
echo ""

# ---- find conda -------------------------------------------------------------------
CONDA=""
for d in "$HOME/miniconda3" "$HOME/opt/miniconda3" "/opt/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" \
         "$HOME/anaconda3" "$HOME/opt/anaconda3" "/opt/anaconda3" \
         "/opt/homebrew/Caskroom/miniconda/base" "/usr/local/Caskroom/miniconda/base" \
         "/opt/homebrew/Caskroom/miniforge/base" "/usr/local/Caskroom/miniforge/base"; do
    if [ -x "$d/bin/conda" ]; then CONDA="$d/bin/conda"; break; fi
done
if [ -z "$CONDA" ]; then CONDA="$(command -v conda || true)"; fi
if [ -z "$CONDA" ]; then
    echo "Miniconda was not found. Install it from https://docs.conda.io/en/latest/miniconda.html and run this again."
    read -n 1 -s -r -p "Press any key to close."; exit 1
fi
echo "Using conda: $CONDA"

# ---- create or update the environment --------------------------------------------
if "$CONDA" env list | grep -qE '^chatlas[[:space:]]'; then
    echo "Updating the existing \"chatlas\" environment..."
    "$CONDA" env update -n chatlas -f environment.yml --prune
else
    echo "Creating the \"chatlas\" environment - this takes a few minutes..."
    "$CONDA" env create -n chatlas -f environment.yml
fi
ENVDIR="$("$CONDA" run -n chatlas python -c 'import sys; print(sys.prefix)')"
echo "Environment: $ENVDIR"

# ---- install the app ----------------------------------------------------------------
"$ENVDIR/bin/python" -m pip install --no-deps --upgrade .

# ---- data folder, app bundle, launcher -------------------------------------------
DATA="$HOME/ChATlas"
mkdir -p "$DATA"
APP="$HOME/Applications/ChATlas.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp chatlas/assets/chatlas.icns "$APP/Contents/Resources/chatlas.icns"
cat > "$APP/Contents/MacOS/ChATlas" <<LAUNCH
#!/bin/bash
cd "$DATA"
exec "$ENVDIR/bin/python" -m chatlas
LAUNCH
chmod +x "$APP/Contents/MacOS/ChATlas"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>ChATlas</string>
  <key>CFBundleDisplayName</key><string>ChATlas</string>
  <key>CFBundleIdentifier</key><string>hu.pte.chatlas</string>
  <key>CFBundleExecutable</key><string>ChATlas</string>
  <key>CFBundleIconFile</key><string>chatlas</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$("$ENVDIR/bin/python" -c 'import chatlas; print(chatlas.__version__)')</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

cat > "$DATA/ChATlas.command" <<CMD
#!/bin/bash
cd "$DATA"
exec "$ENVDIR/bin/python" -m chatlas
CMD
chmod +x "$DATA/ChATlas.command"

echo ""
echo "   Done!  ChATlas is in ~/Applications (drag it to the Dock if you like),"
echo "   or run  $DATA/ChATlas.command"
echo ""
echo "   First time: open the Settings tab, paste your CAVE token and click \"Save token\"."
echo ""
read -n 1 -s -r -p "Press any key to close."

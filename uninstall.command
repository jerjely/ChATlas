#!/bin/bash
# Removes the "chatlas" conda environment and the app; keeps ~/ChATlas (settings, mesh cache, outputs).
CONDA=""
for d in "$HOME/miniconda3" "$HOME/opt/miniconda3" "/opt/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" \
         "$HOME/anaconda3" "$HOME/opt/anaconda3" "/opt/anaconda3" \
         "/opt/homebrew/Caskroom/miniconda/base" "/usr/local/Caskroom/miniconda/base"; do
    if [ -x "$d/bin/conda" ]; then CONDA="$d/bin/conda"; break; fi
done
[ -z "$CONDA" ] && CONDA="$(command -v conda || true)"
echo "This removes the \"chatlas\" environment and ~/Applications/ChATlas.app."
echo "Your data folder ~/ChATlas (settings, mesh cache, outputs) is kept."
read -n 1 -s -r -p "Press any key to continue, or close this window to cancel."
[ -n "$CONDA" ] && "$CONDA" env remove -n chatlas -y
rm -rf "$HOME/Applications/ChATlas.app" "$HOME/ChATlas/ChATlas.command"
echo ""; echo "Removed."

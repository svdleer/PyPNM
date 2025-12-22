#!/usr/bin/env bash
set -euo pipefail

# install_py_path.sh — Append PYTHONPATH exports to your shell startup file.
# Usage: ./install_py_path.sh [PROJECT_ROOT]

if [[ -n "${1-}" ]]; then
  PROJECT_ROOT="$1"
else
  PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

SRC_PATH="$PROJECT_ROOT/src"
BASH_EXPORT="export PYTHONPATH=\"\$PYTHONPATH:$SRC_PATH\""
FISH_EXPORT="set -gx PYTHONPATH \$PYTHONPATH $SRC_PATH"

if [[ "${SHELL##*/}" == "fish" ]]; then
  RC="$HOME/.config/fish/config.fish";    LINE="$FISH_EXPORT"
elif [[ -f "$HOME/.zshrc" ]]; then
  RC="$HOME/.zshrc";                      LINE="$BASH_EXPORT"
elif [[ -f "$HOME/.bashrc" ]]; then
  RC="$HOME/.bashrc";                     LINE="$BASH_EXPORT"
elif [[ -f "$HOME/.bash_profile" ]]; then
  RC="$HOME/.bash_profile";               LINE="$BASH_EXPORT"
else
  echo "⚠️  No rc file found. Add manually: $BASH_EXPORT"
  exit 1
fi

echo "👉 Appending PYTHONPATH to $RC (if not already present)…"
if ! grep -F "$SRC_PATH" "$RC" &>/dev/null; then
  {
    echo ""
    echo "# >>> Added by install_py_path.sh >>>"
    echo "$LINE"
    echo "# <<< End install_py_path.sh <<<"
  } >> "$RC"
  echo "✅ Added to $RC"
else
  echo "⚠️  $SRC_PATH already in $RC; no changes made."
fi

echo
echo "Next:  source $RC   then  echo \$PYTHONPATH"

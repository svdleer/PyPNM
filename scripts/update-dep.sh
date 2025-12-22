#!/usr/bin/env bash
set -euo pipefail

# 1. regenerate requirements.txt from actual imports
echo "🔍 Scanning imports…"
pip install --quiet pipreqs
pipreqs . --force --ignore .env,dist,build

# 2. sync into pyproject.toml
echo "✏️  Syncing into pyproject.toml…"
python update_deps.py --toml pyproject.toml

# 3. install any new deps
echo "📦 Installing new dependencies…"
pip install -r requirements.txt

echo "✅ Dependencies updated."

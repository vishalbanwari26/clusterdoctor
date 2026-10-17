#!/usr/bin/env bash
# Push this project to a Hugging Face Docker Space.
# Usage: scripts/deploy_space.sh <hf-username>/<space-name>
# Create the Space first (huggingface.co/new-space, SDK: Docker, blank). Git will ask for your username and a
# WRITE access token as the password. Set NEBIUS_API_KEY as a Space *secret* in the Space settings, never in git.
set -euo pipefail
SPACE="${1:?usage: deploy_space.sh <hf-username>/<space-name>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
git clone "https://huggingface.co/spaces/${SPACE}" "$TMP/space"
cd "$TMP/space"
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp "$ROOT"/{Dockerfile,.dockerignore,pyproject.toml,uv.lock,LICENSE} .
cp -R "$ROOT"/{src,data} .
mkdir web && cp -R "$ROOT"/web/{index.html,package.json,package-lock.json,vite.config.js,src} web/
cp "$ROOT/space/README.md" README.md
git add -A
git commit -m "Deploy ClusterDoctor" || echo "nothing to commit"
git push
echo "Pushed. Build logs: https://huggingface.co/spaces/${SPACE}"

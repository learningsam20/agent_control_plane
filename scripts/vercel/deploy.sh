#!/bin/sh
# Deploys the control plane to Vercel. The Dockerfile.vercel file at the repo
# root is auto-detected and built on Vercel Fluid compute.
#
# Requires the Vercel CLI:
#   npm install -g vercel && vercel login
#
# One-time env setup (Vercel containers are stateless; SQLite reseeds demo data
# on each instance, so this is best as a shareable demo):
#   vercel env add LLM_MODEL production        # openrouter/anthropic/claude-3.5-sonnet
#   vercel env add LLM_API_KEY production      # sk-or-v1-...
#   vercel env add CONTROLPLANE_POLICY_ENGINE production   # native
#   vercel env add SECRET_KEY production
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! command -v vercel >/dev/null 2>&1; then
  echo "Vercel CLI not found. Install it and re-run:"
  echo "  npm install -g vercel && vercel login"
  exit 1
fi

exec vercel --prod "$@"

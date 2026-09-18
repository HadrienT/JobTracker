#!/bin/sh
# Runs from /docker-entrypoint.d/ on every container start (blueprint/wp/WP15-deploy.md §3).
#
# Changing JT_PUBLIC_API_BASE is a container restart, not an image rebuild — which is
# the whole point: Vite inlines VITE_* at build time, so an image built with a URL in
# it can't be moved and, sooner or later, ends up carrying a secret in its bundle.
set -eu

mkdir -p /tmp/jt
# JSON-encode via the shell's printf so a quote or backslash in the value can't break
# out of the string (the value is operator-set, but a config file shouldn't be an injection point).
api_base=$(printf '%s' "${JT_PUBLIC_API_BASE:-/api}" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf 'window.__JT_CONFIG__ = { apiBase: "%s" };\n' "$api_base" > /tmp/jt/config.js
echo "40-jt-config: apiBase=${JT_PUBLIC_API_BASE:-/api}"

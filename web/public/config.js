// Local-dev default, read by `client.ts` as `window.__JT_CONFIG__` (blueprint/12-WEB-UI.md
// §9). In production this file is generated and overwritten by the nginx
// entrypoint at container start (blueprint/wp/WP15-deploy.md) — never edit
// VITE_* env vars to point at a different API, edit this file's apiBase.
window.__JT_CONFIG__ = { apiBase: 'http://127.0.0.1:8100' }

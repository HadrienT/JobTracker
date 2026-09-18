// Local-dev default, read by `client.ts` as `window.__JT_CONFIG__` (blueprint/12-WEB-UI.md
// §9). In production this file is not served: the nginx image regenerates /config.js at
// container start from JT_PUBLIC_API_BASE (web/40-jt-config.sh). The API base is never a
// build-time variable — edit this file's apiBase for local development instead.
window.__JT_CONFIG__ = { apiBase: 'http://127.0.0.1:8100' }

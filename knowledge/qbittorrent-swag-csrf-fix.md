---
id: qbittorrent-swag-csrf-fix
type: knowledge
date: 2026-07-17
tags: [qbittorrent, swag, nginx, reverse-proxy, csrf, homelab]
importance: medium
source: "relocated from ~/.claude harness memory 2026-07-25 (Dominion integration)"
---

# qBittorrent 5.x behind SWAG — CSRF Origin/Host mismatch breaks WebUI login

On 2026-07-17, WebUI login to qBittorrent (torrents.home.local) started returning 401. Root cause: qBittorrent was upgraded to 5.2.2 (LSIO, ~2026-06-21) which added a strict CSRF check comparing the browser's `Origin` header against the `Host` header it receives. SWAG's nginx was sending `Host: qbittorrent:8080` (internal upstream) while the browser sent `Origin: https://torrents.home.local` → mismatch → login rejected. Symptom in log: `WebUI: Origin header & Target origin mismatch!` in `/etc/container_configs/media_system/qbittorrent/config/logs/qbittorrent.log`. Internal API clients (sonarr/radarr/stremio) were unaffected because they send no Origin header.

**Fix:** In `/etc/container_configs/reverse_proxy/swag/config/nginx/site-confs/qbittorrent.subdomain.conf`, change every `proxy_set_header Host $upstream_app:$upstream_port;` to `proxy_set_header Host $host;`. NOTE: there are ~8 location blocks (`/`, `/api`, `/command`, `/css`, `/query`, `/login`, `/sync`, `/scripts`) — ALL must be changed, not just `/`. The login POST hits `/api/v2/auth/login`, so fixing only `/` leaves the 401. Then `docker exec swag nginx -t && docker exec swag nginx -s reload`.

Alternative fixes if the Host approach ever regresses: set `WebUI\ServerDomains` to the real domain (currently `*`), or disable the CSRF/host-header validation in qBittorrent Options → WebUI.

Container IPs on the docker bridge get reassigned on restart, so the "Source IP" in mismatch log lines (was 172.18.0.23 = SWAG at the time) is not a stable identifier. Related: `nextcloud-nginx-config-drift` (reverse-proxy config drift).

---
id: nextcloud-nginx-config-drift
type: knowledge
date: 2026-07-17
tags: [nextcloud, nginx, config-drift, homelab, maintenance]
importance: low
source: "relocated from ~/.claude harness memory 2026-07-25 (Dominion integration)"
---

# Nextcloud nginx config files need updating to newer samples (pending)

The linuxserver/nextcloud container (34.0.0-ls438) ships updated sample configs that differ from the ones currently in `/etc/container_configs/baadal/nextcloud/nginx/`:

| File | Current date | Sample date |
|------|-------------|-------------|
| `nginx/ssl.conf` | 2022-08-20 | 2025-07-18 |
| `nginx/site-confs/default.conf` | 2022-08-20 | 2025-07-10 |
| `nginx/nginx.conf` | 2022-08-16 | 2025-05-31 |

Also: `site-confs/default` (no `.conf` extension) is present and should either be renamed to `default.conf` or removed — nginx.conf only includes `*.conf`.

**Why:** linuxserver image logs this on every container start as a warning. The old http2 directive syntax (`listen ... http2`) was deprecated upstream; newer sample likely uses the new form.

**How to apply:** Before the next nextcloud maintenance window, diff each file against the sample (available in the running container at the same paths but under `/defaults/`) and merge any custom config (mostly the http2 listen lines and any custom location blocks).

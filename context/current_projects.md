---
id: current-projects
type: context
date: 2026-06-21
tags: [projects, homelab, docker, current-work]
importance: high
---

# Current Project Context

## Active: requiem branch (phase 2)
- **remote-shell**: `requiem/phase-2/remote-shell/` — review, reorganize, redeploy pending
- **finances**: `requiem/phase-2/finances/` — actual-budget + actual-helper + n8n stack

## Active: Full homelab upgrade sweep (2026-06-21)
Comprehensive upgrade of all Docker services across REQUIEM + GENESIS.

### Genesis upgrade status
- [x] LLM stack: open-webui, ollama, searxng — pulled & restarted; smoke tested
- [x] llm_redis (valkey:8-alpine) — pulled latest 8-alpine; **TODO: bump to 9-alpine**
- [x] immich-heavylifting: immich_microservices, immich_machine_learning → v2.7.5
- [x] downloaders: prowlarr — updated
- [x] connectivity: tailscale — already current
- [x] syncthing — updated
- [x] stats: influxdb, telegraf — already current
- [x] maintenance: dozzle-agent v8 → v10.6.6 — committed
- [ ] bots: lusci (eclipse-temurin:21-jre-alpine) — pull image (jar update separate) [ARCHIVED — not pursuing]

### REQUIEM upgrade status — COMPLETE (2026-06-21)
- [x] Immich v2.5.6 → v2.7.5
- [x] dozzle + dozzle-agent v8 → v10.6.6
- [x] locally built: stremio-web, navidrome, excalidraw, excalidraw-room — rebuilt + deployed
- [x] all pull-based images pulled + restarted
- [x] headscale config migrated (ephemeral_node_inactivity_timeout → node.ephemeral.inactivity_timeout, randomize_client_port removed)
- [x] finances compose committed to git (was untracked)
- [ ] SKIP: postgres:14 → 17 (nextcloud) — major migration, needs explicit planning
- [x] remote-shell: hardened + rebuilt + committed (2026-06-21)

### Known issues (post-upgrade)
- actual-helper: two fixes applied locally (navigator polyfill image + ACTUAL_SERVER_URL port 5006→3847); now healthy. Navigator polyfill PR open: https://github.com/tm9k1/actual-helper/pull/1
- Genesis: llm_redis (valkey) — already at 9-alpine in compose (TODO was stale); consumer is searxng

### Key findings
- immich .env is gitignored (has secrets) — version changes not tracked in git
- Dozzle v10 deprecates DOZZLE_AGENT_PORT env var (now warns); harmless
- genesis compose files at /home/tm9k1/docker/compose-files/.git; use `git -C /home/tm9k1/docker/compose-files` for genesis git ops
- headscale :stable had breaking config change — new version globs all *.yaml in /etc/headscale/, picked up old example file `1config.yaml`; fixed by renaming to `1config.yaml.bak`
- always check headscale logs immediately after upgrade

## Queued: postgres:14 → 17 migration (nextcloud)
- **After** current upgrade sweep is fully complete
- Compose: `requiem/phase-1/cloud/docker-compose.yml`, service `postgres`, `NC_POSTGRES_VERSION=14`
- Requires: dump with pg_dumpall, spin up postgres:17 fresh, restore, update .env, test nextcloud
- Do NOT do this as a simple `docker pull` — major version needs explicit migration steps

## Infrastructure Conventions
- Config files: `/etc/container_configs/<service>/`
- Compose files: `/home/tm9k1/docker/compose-files/`
- Branch per feature; main branch `main`
- .env files are gitignored (secrets) — only compose YAMLs tracked
- REQUIEM git: run from `/home/tm9k1/docker/compose-files/` (current working dir)
- Genesis git: use `git -C /home/tm9k1/docker/compose-files` over SSH

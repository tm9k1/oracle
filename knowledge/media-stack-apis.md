# Media Stack — Reaching APIs From the Host

How to talk to qBittorrent and Jellyfin programmatically from REQUIEM's host shell.
Both run as Docker containers on the `global_docker_network` bridge (no host port publish —
reach them by container IP on the bridge, not `localhost`).

## Finding a container's bridge IP
```
docker inspect <name> --format '{{.NetworkSettings.Networks.global_docker_network.IPAddress}}'
```
IPs are dynamic across restarts — always re-resolve, don't hardcode.

## qBittorrent

- WebUI on port **8080** (container-internal). Compose:
  `~/docker/compose-files/requiem/phase-1/downloaders/` (`.env` has PUID/PGID/paths, NOT creds).
- Config on host: `/etc/container_configs/media_system/qbittorrent/config/qBittorrent.conf`.
  - `WebUI\Username=tm9k1`; password is PBKDF2-hashed (`WebUI\Password_PBKDF2=...`) — not recoverable.
- Downloads root (host): `/mnt/hdd/downloads/torrent/` → `complete/` and `incomplete/`.
  Inside the container this is `/downloads/complete` etc. (paths in the API are container paths).

### Auth + API
```
# login → sets cookie
curl -c cookies.txt -X POST "http://<ip>:8080/api/v2/auth/login" \
  --data-urlencode "username=tm9k1" --data-urlencode "password=<pw>"
# then reuse the QBT_SID cookie:
curl -H "Cookie: QBT_SID_8080=<sid>" "http://<ip>:8080/api/v2/torrents/info"
```
- `torrents/info?filter=downloading` — filter states. States seen: `downloading`, `queuedDL`,
  `forcedDL`, `stoppedUP` (done+seeding stopped), `missingFiles` (files gone from disk).
- Delete entry: `POST /api/v2/torrents/delete` with `hashes=<hash>&deleteFiles=true`
  (`deleteFiles=false` keeps the files on disk).

### GOTCHAS
- **Ban on failed logins**: ~5 wrong passwords → "IP address has been banned". The ban is
  in-memory — **restart the container to clear it** (`docker restart qbittorrent`), then wait
  ~15–20s for the WebUI to come back before retrying.
- `localhost` auth from inside the container is NOT bypassed by default (returns 403) — you
  still need real credentials.
- Successful login returns HTTP 204 (empty body), not "Ok." — check the status code / cookie.

## Jellyfin

- Web/API on port **8096**. Config on host:
  `/etc/container_configs/media_system/jellyfin/`.
- TV library root: `/mnt/hdd/media/tv_shows/`. Jellyfin auto-adds `folder.jpg`/`backdrop.jpg`
  artwork into show dirs during scans.

### API key + trigger a scan
```
# pull an existing API token from the DB (no UI needed):
sqlite3 /etc/container_configs/media_system/jellyfin/data/data/jellyfin.db \
  "SELECT AccessToken FROM ApiKeys LIMIT 5;"
# trigger a full library refresh:
curl -X POST "http://<ip>:8096/Library/Refresh" -H "X-Emby-Token: <token>"
```
Returns HTTP 204 on accept; scan runs async.

## TV library layout (for reorganizing downloads)
- Jellyfin expects `<Show Name>/Season NN/` with episodes inside.
- TVDB is the metadata source; look up a series' season/episode split via its TVDB id before
  bucketing loose episode files (e.g. Shin Chan 2006 = 3 seasons × 26 eps = S01 01–26,
  S02 27–52, S03 53–78).

## Related
- [[oracle-bot]] — Oracle often gets asked to manage these

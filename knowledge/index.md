---
id: knowledge-index
type: knowledge-index
date: 2026-08-29
tags: [knowledge-base, operational, systems]
importance: high
---

# Knowledge Base

Operational and systems-level facts about the Oracle project and the REQUIEM homelab.
Distinct from `stars/` (behavioral patterns to repeat) and `scars/` (mistakes to avoid) —
this is durable technical reference: how things are wired, how to invoke them, where the gotchas are.

This layer is **REQUIEM's operational annex** that Dominion links to (see the
Dominion `mind/ref_requiem_ops_annex.md` pointer). Durable, planning-relevant
device facts live in Dominion entities; the how-to-fix-it detail lives here.

## Index
- [oracle-bot](oracle-bot.md) — Oracle Discord bot: architecture, modular AI backends, session-aware routing, restart
- [agy-cli-invocation](agy-cli-invocation.md) — how `agy -p` is driven programmatically (flags, streaming, sessions)
- [claude-cli-invocation](claude-cli-invocation.md) — legacy: how `claude -p` is driven programmatically
- [media-stack-apis](media-stack-apis.md) — qBittorrent + Jellyfin: reaching their APIs from the host
- [qbittorrent-swag-csrf-fix](qbittorrent-swag-csrf-fix.md) — qBit 5.x Origin/Host CSRF mismatch behind SWAG; fix Host header in all nginx blocks
- [nextcloud-nginx-config-drift](nextcloud-nginx-config-drift.md) — pending: nextcloud nginx sample configs drifted since 2022

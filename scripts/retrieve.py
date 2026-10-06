#!/usr/bin/env python3
"""
RAG retrieval engine for the .ai knowledge base.
Uses TF-IDF-style scoring + tag matching + recency weighting.
"""
import re
import json
import math
from pathlib import Path
from datetime import datetime, date
from typing import Optional

import os
KB_DIR = Path(os.environ.get("ORACLE_DIR") or Path(__file__).resolve().parent.parent)


def _get_vault_dir() -> Path:
    env_vault = os.environ.get("KB_VAULT_PATH")
    if env_vault:
        return Path(env_vault)
    cfg_path = KB_DIR / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            vpath = cfg.get("kb", {}).get("vault_path")
            if vpath and Path(vpath).exists():
                return Path(vpath)
        except Exception:
            pass
    if Path("/mnt/hdd/notes/Dominion").exists():
        return Path("/mnt/hdd/notes/Dominion")
    return KB_DIR / "knowledge"


DOMINION_DIR = _get_vault_dir()

# ── Parsing ─────────────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-ish frontmatter and body from a markdown file."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].strip()
    meta = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            meta[k] = v
    return meta, body


def get_all_documents() -> list[Path]:
    """All searchable docs: Authoritative vault + the operational annex."""
    docs = []
    # Vault: user context (mind/) + entity graph (facts), or general markdown hierarchy
    if DOMINION_DIR.exists():
        found_structured = False
        if (DOMINION_DIR / "mind").exists():
            docs.extend((DOMINION_DIR / "mind").glob("*.md"))
            found_structured = True
        if (DOMINION_DIR / "entities").exists():
            docs.extend((DOMINION_DIR / "entities").glob("*.md"))
            found_structured = True
        if not found_structured:
            docs.extend(list(DOMINION_DIR.glob("**/*.md"))[:200])

    # Operational annex: earned patterns/mistakes, homelab runbooks, user stub.
    for subdir in ["stars", "scars", "context", "knowledge"]:
        docs.extend((KB_DIR / subdir).glob("*.md"))
    if (KB_DIR / "USER.md").exists():
        docs.append(KB_DIR / "USER.md")
    return docs


# ── Scoring ─────────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def recency_score(date_str: str) -> float:
    """Newer documents get a small bonus (0-1 range)."""
    try:
        doc_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        days_old = (date.today() - doc_date).days
        return math.exp(-days_old / 180)  # half-life ~6 months
    except Exception:
        return 0.0


def importance_weight(imp: str) -> float:
    return {"high": 3.0, "medium": 2.0, "low": 1.0}.get(imp, 2.0)


def bm25_score(query_terms: list[str], doc_terms: list[str], k1: float = 1.5, b: float = 0.75, avg_dl: float = 300) -> float:
    """Simplified BM25 scoring."""
    dl = len(doc_terms)
    score = 0.0
    doc_tf = {}
    for t in doc_terms:
        doc_tf[t] = doc_tf.get(t, 0) + 1

    for term in query_terms:
        tf = doc_tf.get(term, 0)
        if tf == 0:
            continue
        norm_tf = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
        score += norm_tf
    return score


# ── Core API ─────────────────────────────────────────────────────────────────

def retrieve_context(query: str, top_k: int = 6) -> list[dict]:
    """
    Return top-k most relevant documents for a query.
    Each result: {'path': ..., 'meta': ..., 'body': ..., 'score': ...}
    """
    query_terms = tokenize(query)
    if not query_terms:
        return []

    results = []
    for path in get_all_documents():
        try:
            text = path.read_text()
        except Exception:
            continue

        meta, body = parse_frontmatter(text)
        doc_terms = tokenize(text)

        bm25 = bm25_score(query_terms, doc_terms)
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        tag_bonus = sum(5.0 for qt in query_terms if qt in tags)
        recency = recency_score(meta.get("date", "2020-01-01"))
        weight = importance_weight(meta.get("importance", "medium"))

        score = (bm25 + tag_bonus) * weight + recency * 2
        if score > 0:
            results.append({
                "path": str(path),
                "meta": meta,
                "body": body,
                "score": score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def get_core_context(max_chars: int = 12000) -> str:
    """
    Always-loaded context. Authoritative layer from Dominion (user context, how to
    work with the operator, the fleet roster); operational recency from the annex (recent
    stars/scars, current work). Degrades gracefully if the Dominion vault isn't
    mounted. Truncated to max_chars.
    """
    sections = []

    def _load(path: Path, label: str):
        try:
            text = path.read_text()
            _, body = parse_frontmatter(text)
            return f"## {label}\n{body}"
        except Exception:
            return ""

    # Authoritative: Dominion mind/ (user context, standing feedback) + fleet roster.
    if DOMINION_DIR.exists():
        mind = DOMINION_DIR / "mind"
        sections.append(_load(mind / "about-me.md", "User Context (Dominion)"))
        sections.append(_load(mind / "feedback_homelab_ops.md", "How to work on the homelab"))
        sections.append(_load(mind / "feedback_lean_emergence.md", "Standing preference: lean / emergence"))
        sections.append(_load(DOMINION_DIR / "CENSUS.md", "Fleet & entities (census)"))
    else:
        # Vault not mounted — fall back to the annex stub so context isn't empty.
        sections.append(_load(KB_DIR / "USER.md",
                              "User Context (annex fallback — Dominion vault not mounted)"))

    # Operational recency from the annex.
    stars = sorted((KB_DIR / "stars").glob("2*.md"), reverse=True)[:3]
    if stars:
        sections.append("## Operational patterns (recent stars)\n"
                        + "\n\n".join(_load(p, p.stem) for p in stars))
    scars = sorted((KB_DIR / "scars").glob("2*.md"), reverse=True)[:3]
    if scars:
        sections.append("## Operational mistakes to avoid (recent scars)\n"
                        + "\n\n".join(_load(p, p.stem) for p in scars))
    sections.append(_load(KB_DIR / "context" / "current_projects.md", "Current work (annex)"))

    combined = "\n\n---\n\n".join(s for s in sections if s)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[...truncated for context window...]"
    return combined


def format_retrieved(results: list[dict], max_chars: int = 6000) -> str:
    """Format retrieval results into a context string."""
    if not results:
        return ""
    parts = []
    total = 0
    for r in results:
        label = r["meta"].get("id", Path(r["path"]).stem)
        chunk = f"### [{label}]\n{r['body']}"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "docker homelab"
    print("=== Core Context ===")
    print(get_core_context()[:500], "...")
    print("\n=== Retrieved ===")
    results = retrieve_context(query)
    for r in results:
        print(f"  [{r['score']:.2f}] {r['path']}")

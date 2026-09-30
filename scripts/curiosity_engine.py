#!/usr/bin/env python3
"""
Dominion Curiosity Engine for Oracle.

Surveys Dominion weekly (entities, mind notes, open questions, and planning loops)
and proactively asks the user 1-2 conversational questions per day via Discord DM to
expand Dominion's knowledge base.

Maintains conversational continuity:
- Unanswered questions are preserved in pending state and not buried or forgotten.
- Maintains an open ear: answers unrelated user queries immediately while keeping
  the active curiosity question alive.
- Stages user answers into Dominion staging inbox (/mnt/hdd/notes/Dominion/mind/inbox/)
  for steward review (Constitution Article XII).
"""
import copy
import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("curiosity_engine")

DOMINION_DEFAULT_ROOT = Path("/mnt/hdd/notes/Dominion")
DEFAULT_STATE_FILE = Path("/home/tm9k1/.ai/curiosity_state.json")
DEFAULT_CONFIG_FILE = Path("/home/tm9k1/.ai/config.json")


def clean_markdown_links(text: str) -> str:
    """Strip [[wiki-links]] and [markdown](links) to clean prose."""
    # Convert [[link|alias]] -> alias
    text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)
    # Convert [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Clean bold / italics markers
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


@dataclass
class CuriosityQuestion:
    id: str
    topic: str
    target_file: str
    question: str
    context: str
    category: str  # "open_question", "gadget", "health", "family", "project", "routine", "general"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CuriosityQuestion":
        return cls(
            id=data["id"],
            topic=data["topic"],
            target_file=data.get("target_file", ""),
            question=data["question"],
            context=data.get("context", ""),
            category=data.get("category", "general"),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class ActiveQuestion:
    id: str
    topic: str
    target_file: str
    question: str
    context: str
    category: str
    asked_at: float
    message_id: Optional[int] = None
    channel_id: Optional[str] = None
    status: str = "pending"  # "pending", "answered", "skipped"
    nudge_count: int = 0
    last_nudged_at: Optional[float] = None
    user_answer: Optional[str] = None
    answered_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ActiveQuestion":
        return cls(
            id=data["id"],
            topic=data["topic"],
            target_file=data.get("target_file", ""),
            question=data["question"],
            context=data.get("context", ""),
            category=data.get("category", "general"),
            asked_at=data.get("asked_at", time.time()),
            message_id=data.get("message_id"),
            channel_id=data.get("channel_id"),
            status=data.get("status", "pending"),
            nudge_count=data.get("nudge_count", 0),
            last_nudged_at=data.get("last_nudged_at"),
            user_answer=data.get("user_answer"),
            answered_at=data.get("answered_at"),
        )


class DominionSurveyor:
    """Surveys Dominion markdown files for open loops, gaps, and curiosity prompts."""

    def __init__(self, dominion_root: Path):
        self.root = dominion_root
        self.entities_dir = dominion_root / "entities"
        self.mind_dir = dominion_root / "mind"
        self.planning_file = dominion_root / "PLANNING-CHAMBER.md"

    def survey_all(self) -> List[CuriosityQuestion]:
        """Run complete survey across entities, mind notes, and planning chamber."""
        questions: List[CuriosityQuestion] = []
        questions.extend(self.survey_entities())
        questions.extend(self.survey_mind_notes())
        questions.extend(self.survey_planning_chamber())
        return self._deduplicate_questions(questions)

    def _deduplicate_questions(self, questions: List[CuriosityQuestion]) -> List[CuriosityQuestion]:
        seen_ids = set()
        unique = []
        for q in questions:
            if q.id not in seen_ids:
                seen_ids.add(q.id)
                unique.append(q)
        return unique

    def survey_entities(self) -> List[CuriosityQuestion]:
        """Scan entities/*.md for ## Open questions and unprobed areas."""
        questions: List[CuriosityQuestion] = []
        if not self.entities_dir.exists():
            return questions

        for file_path in sorted(self.entities_dir.glob("*.md")):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                log.warning("Could not read %s: %s", file_path, e)
                continue

            entity_id = file_path.stem
            entity_title = self._extract_title(content) or entity_id

            # 1. Parse ## Open questions
            open_q_match = re.search(r"##\s*Open questions?(.*?)(?:\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
            if open_q_match:
                section_text = open_q_match.group(1).strip()
                raw_bullets = re.findall(r"^[*-]\s*(.+)$", section_text, re.MULTILINE)
                for bullet in raw_bullets:
                    bullet_clean = clean_markdown_links(bullet.strip())
                    bullet_lower = bullet_clean.lower()

                    # Filter out bullets that explicitly declare nothing open
                    if (
                        not bullet_clean
                        or bullet_lower.startswith("none")
                        or "none load-bearing" in bullet_lower
                        or "the per-holding split was dropped" in bullet_lower
                        or "live numbers are canonical" in bullet_lower
                        or "canonical in the annex" in bullet_lower
                        or "details live in" in bullet_lower
                    ):
                        continue

                    # Turn bullet into a conversational question
                    q_text, q_id = self._formulate_question_from_bullet(entity_id, entity_title, bullet_clean)
                    if q_text:
                        questions.append(
                            CuriosityQuestion(
                                id=q_id,
                                topic=entity_id,
                                target_file=f"entities/{file_path.name}",
                                question=q_text,
                                context=f"From {entity_title} Open questions: {bullet_clean}",
                                category="open_question",
                            )
                        )

            # 2. Domain-specific probes for high-value entities
            probes = self._entity_specific_probes(entity_id, entity_title, content)
            questions.extend(probes)

        return questions

    def _extract_title(self, content: str) -> Optional[str]:
        m_yaml = re.search(r"^title:\s*[\"']?(.*?)[\"']?$", content, re.MULTILINE)
        if m_yaml:
            return m_yaml.group(1).strip()
        m_h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if m_h1:
            return clean_markdown_links(m_h1.group(1).strip())
        return None

    def _formulate_question_from_bullet(self, entity_id: str, title: str, bullet: str) -> Tuple[str, str]:
        slug = re.sub(r"[^a-z0-9]+", "-", bullet.lower()[:35]).strip("-")
        qid = f"openq-{entity_id}-{slug}"
        clean_title = clean_markdown_links(title)

        if bullet.endswith("?"):
            return f"Regarding {clean_title}: {bullet}", qid

        b_clean = bullet.rstrip(".")
        if "other details — not recorded" in bullet.lower():
            return f"Dominion currently has limited details on {clean_title}. Could you share a bit more about what's new with {clean_title}?", f"sparse-{entity_id}"
        elif "whether" in bullet.lower():
            return f"Regarding {clean_title}, Dominion has an open question: {b_clean}. What is the current status?", qid
        else:
            return f"Regarding {clean_title}, Dominion notes: '{b_clean}'. Could you shed some light on this?", qid

    def _entity_specific_probes(self, entity_id: str, title: str, content: str) -> List[CuriosityQuestion]:
        """Targeted inquiries for key entities."""
        probes = []
        if entity_id == "father":
            probes.append(
                CuriosityQuestion(
                    id="father-house-improvements",
                    topic="father",
                    target_file="entities/father.md",
                    question="Dominion notes your father is involved in house improvements. How is that project progressing lately, or what other things is he working on?",
                    context="Father house improvements",
                    category="family",
                )
            )
        elif entity_id == "mother":
            probes.append(
                CuriosityQuestion(
                    id="mother-rental-updates",
                    topic="mother",
                    target_file="entities/mother.md",
                    question="Dominion records your mother managing rental properties. Any recent updates on tenants or property matters you'd like captured?",
                    context="Mother rental property management",
                    category="family",
                )
            )
        elif entity_id == "brother":
            probes.append(
                CuriosityQuestion(
                    id="brother-updates",
                    topic="brother",
                    target_file="entities/brother.md",
                    question="How is your brother doing lately? Anything new in his work or life that Dominion should keep note of?",
                    context="Brother life updates",
                    category="family",
                )
            )
        elif entity_id in ("didi", "sister"):
            probes.append(
                CuriosityQuestion(
                    id="sister-updates",
                    topic=entity_id,
                    target_file=f"entities/{entity_id}.md",
                    question="How is your sister doing? Any family gatherings or news on her side lately?",
                    context="Sister life updates",
                    category="family",
                )
            )
        elif entity_id == "bunker":
            probes.append(
                CuriosityQuestion(
                    id="bunker-drive-model",
                    topic="bunker",
                    target_file="entities/bunker.md",
                    question="BUNKER (your 1 TB offline backup SSD) is still dormant. Do you recall what drive brand/model it is, or have you had a chance to connect it for a quick survey?",
                    context="1 TB offline backup SSD",
                    category="gadget",
                )
            )
        elif entity_id == "new-homelab":
            probes.append(
                CuriosityQuestion(
                    id="new-homelab-timeline",
                    topic="new-homelab",
                    target_file="entities/new-homelab.md",
                    question="You have a proposed homelab expansion to eventually house INFINITY. Have any new hardware picks or location ideas surfaced for that build?",
                    context="New homelab buildout",
                    category="project",
                )
            )
        elif entity_id == "chip":
            probes.append(
                CuriosityQuestion(
                    id="chip-steamdeck-games",
                    topic="chip",
                    target_file="entities/chip.md",
                    question="On CHIP (the Steam Deck), have you or anyone in the house been playing any specific games recently?",
                    context="Steam Deck gaming",
                    category="gadget",
                )
            )
        elif entity_id == "spartan":
            probes.append(
                CuriosityQuestion(
                    id="spartan-tailscale-usage",
                    topic="spartan",
                    target_file="entities/spartan.md",
                    question="On SPARTAN (MacBook Air M4), do you keep Tailscale connected all the time now, or only launch it on-demand when away from the home LAN?",
                    context="SPARTAN Tailscale status",
                    category="gadget",
                )
            )
        elif entity_id == "music-library-enhancement":
            probes.append(
                CuriosityQuestion(
                    id="music-library-recent-albums",
                    topic="music-library-enhancement",
                    target_file="entities/music-library-enhancement.md",
                    question="Have you added any new albums, artists, or genres to your local music collection lately for Navidrome or Jellyfin?",
                    context="Local music collection",
                    category="routine",
                )
            )
        return probes

    def survey_mind_notes(self) -> List[CuriosityQuestion]:
        """Scan mind/*.md for personal habits, gadgets, and life topics."""
        questions: List[CuriosityQuestion] = []
        if not self.mind_dir.exists():
            return questions

        about_me = self.mind_dir / "about-me.md"
        if about_me.exists():
            questions.extend(
                [
                    CuriosityQuestion(
                        id="about-me-health-progress",
                        topic="about-me",
                        target_file="mind/about-me.md",
                        question="Dominion notes your ongoing health and fitness goals. How have your health metrics and diet been feeling lately?",
                        context="Health milestone and lifestyle battle",
                        category="health",
                    ),
                    CuriosityQuestion(
                        id="about-me-sleep-routine",
                        topic="about-me",
                        target_file="mind/about-me.md",
                        question="You've been optimizing your sleep schedule (waking earlier, dialing back late coffee). How has your sleep routine been holding up this week?",
                        context="Sleep schedule and daily routine",
                        category="routine",
                    ),
                    CuriosityQuestion(
                        id="about-me-macos-workflow",
                        topic="about-me",
                        target_file="mind/about-me.md",
                        question="Since macOS has become your primary daily driver with Ubuntu for dual boot experiments, how has that OS balance worked out for your daily workflows?",
                        context="Operating system and desktop workflows",
                        category="routine",
                    ),
                ]
            )

        gadgets = self.mind_dir / "ref_gadget_inventory.md"
        if gadgets.exists():
            questions.extend(
                [
                    CuriosityQuestion(
                        id="gadget-oculus-quest-3",
                        topic="ref-gadget-inventory",
                        target_file="mind/ref_gadget_inventory.md",
                        question="Dominion mentions your Oculus Quest 3 headset. Have you played any fun VR titles recently, or is it taking a break on the shelf?",
                        context="VR gaming with Quest 3",
                        category="gadget",
                    ),
                    CuriosityQuestion(
                        id="gadget-audio-jogging",
                        topic="ref-gadget-inventory",
                        target_file="mind/ref_gadget_inventory.md",
                        question="Between the Snowsky Echo Mini and your KZ ZEX Pro IEMs, how are your jogging and music sessions going?",
                        context="Jogging audio setup",
                        category="gadget",
                    ),
                    CuriosityQuestion(
                        id="gadget-esp32-projects",
                        topic="ref-gadget-inventory",
                        target_file="mind/ref_gadget_inventory.md",
                        question="You have a couple ESP32 boards and relays on your workbench. Any home automation ideas or sensor projects you're planning to wire up?",
                        context="ESP32 microcontroller bench kit",
                        category="project",
                    ),
                    CuriosityQuestion(
                        id="gadget-hotwheels-collection",
                        topic="ref-gadget-inventory",
                        target_file="mind/ref_gadget_inventory.md",
                        question="Dominion mentions your Hot Wheels collection! Any favorite casting you particularly cherish or new additions lately?",
                        context="Hot Wheels and non-tech hobby collections",
                        category="general",
                    ),
                    CuriosityQuestion(
                        id="gadget-chair-comfort",
                        topic="ref-gadget-inventory",
                        target_file="mind/ref_gadget_inventory.md",
                        question="How is the Green Soul Monster chair holding up for your back and posture during long desk sessions?",
                        context="Desk setup ergonomics",
                        category="routine",
                    ),
                ]
            )

        return questions

    def survey_planning_chamber(self) -> List[CuriosityQuestion]:
        """Scan PLANNING-CHAMBER.md for active loops and life events."""
        questions: List[CuriosityQuestion] = []
        if not self.planning_file.exists():
            return questions

        try:
            content = self.planning_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return questions

        if "2026-11-25" in content or "wedding" in content.lower():
            questions.append(
                CuriosityQuestion(
                    id="planning-wedding-prep",
                    topic="wedding",
                    target_file="PLANNING-CHAMBER.md",
                    question="With wedding preparations tracked in Dominion, how are the arrangements and milestones progressing?",
                    context="Wedding preparations and milestone tracking",
                    category="family",
                )
            )

        if "migration" in content.lower():
            questions.append(
                CuriosityQuestion(
                    id="planning-migration-aspirations",
                    topic="migration",
                    target_file="PLANNING-CHAMBER.md",
                    question="Dominion notes migration and career goals in the planning chamber. Are international moves or studies still something on your horizon, or has focus shifted?",
                    context="Migration aspirations and long-term planning",
                    category="project",
                )
            )

        if "syncthing" in content.lower() and "versioning" in content.lower():
            questions.append(
                CuriosityQuestion(
                    id="planning-syncthing-versioning",
                    topic="syncthing-versioning",
                    target_file="PLANNING-CHAMBER.md",
                    question="In the Planning Chamber, there was an open decision on enabling Syncthing file versioning on the notes folder. Did you settle on an approach for that?",
                    context="Dominion vault backup and Syncthing versioning posture",
                    category="project",
                )
            )

        return questions


class CuriosityEngine:
    """Orchestrates curiosity questions, cadences, conversational state, and inbox staging."""

    def __init__(
        self,
        dominion_root: Optional[Path] = None,
        state_path: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ):
        self.dominion_root = Path(dominion_root or DOMINION_DEFAULT_ROOT)
        self.inbox_dir = self.dominion_root / "mind" / "inbox"
        self.state_path = Path(state_path or DEFAULT_STATE_FILE)
        self.config_path = Path(config_path or DEFAULT_CONFIG_FILE)

        self.surveyor = DominionSurveyor(self.dominion_root)
        self._cfg = self._load_config()

        # Cadence parameters
        self.enabled = bool(self._cfg.get("enabled", True))
        self.questions_per_day = int(self._cfg.get("questions_per_day", 2))
        self.min_gap_seconds = float(self._cfg.get("min_gap_hours", 6)) * 3600
        self.active_hours_start = int(self._cfg.get("active_hours_start", 10))  # 10 AM
        self.active_hours_end = int(self._cfg.get("active_hours_end", 22))      # 10 PM
        self.survey_interval_seconds = float(self._cfg.get("survey_interval_days", 7)) * 86400
        self.nudge_after_seconds = float(self._cfg.get("nudge_after_hours", 24)) * 3600
        self.max_nudges = int(self._cfg.get("max_nudges", 1))

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return data.get("curiosity", {})
            except Exception as e:
                log.warning("Could not read curiosity config: %s", e)
        return {}

    def load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Failed to parse %s: %s", self.state_path, e)
        return {
            "last_survey_at": 0,
            "queued_questions": [],
            "active_question": None,
            "history": [],
            "daily_stats": {"date": "", "count": 0},
        }

    def save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    def get_active_question(self) -> Optional[ActiveQuestion]:
        st = self.load_state()
        aq = st.get("active_question")
        if aq:
            return ActiveQuestion.from_dict(aq)
        return None

    def run_survey(self, force: bool = False) -> List[CuriosityQuestion]:
        """Perform a weekly survey of Dominion and replenish the curiosity queue."""
        state = self.load_state()
        now = time.time()
        last_survey = state.get("last_survey_at", 0)

        if not force and (now - last_survey) < self.survey_interval_seconds and state.get("queued_questions"):
            return [CuriosityQuestion.from_dict(d) for d in state["queued_questions"]]

        log.info("Running Dominion curiosity survey (root: %s)", self.dominion_root)
        discovered = self.surveyor.survey_all()

        # Build list of previously asked/queued IDs to avoid re-asking recent questions
        history_ids = {h.get("id") for h in state.get("history", [])}
        active_id = state.get("active_question", {}).get("id") if state.get("active_question") else None
        existing_queued_ids = {q.get("id") for q in state.get("queued_questions", [])}

        new_pool = []
        for q in discovered:
            if q.id in history_ids or q.id == active_id or q.id in existing_queued_ids:
                continue
            new_pool.append(q)

        # Mix with existing queued questions and shuffle
        existing_queued = [CuriosityQuestion.from_dict(d) for d in state.get("queued_questions", [])]
        combined = existing_queued + new_pool

        # Shuffle to provide delightful variety across categories
        random.seed(int(now))
        random.shuffle(combined)

        state["queued_questions"] = [q.to_dict() for q in combined]
        state["last_survey_at"] = now
        self.save_state(state)
        log.info("Survey completed. Queued questions count: %d", len(combined))
        return combined

    def should_ask_now(self, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Evaluate if Oracle should ask a question right now.
        Returns (should_act, reason):
        - (True, "ask") -> Time to ask next question.
        - (True, "nudge") -> Time to gently re-prompt pending question.
        - (False, <reason>) -> Don't ask right now.
        """
        if not self.enabled:
            return False, "curiosity_disabled"

        now_dt = now_dt or datetime.now()
        now_ts = now_dt.timestamp()
        today_str = now_dt.strftime("%Y-%m-%d")
        current_hour = now_dt.hour

        state = self.load_state()
        aq_data = state.get("active_question")

        # ── Check active question (Conversation continuity discipline) ─────────
        if aq_data and aq_data.get("status") == "pending":
            aq = ActiveQuestion.from_dict(aq_data)
            # Check if gentle nudge is due
            elapsed_since_asked = now_ts - aq.asked_at
            if (
                self.active_hours_start <= current_hour < self.active_hours_end
                and elapsed_since_asked >= self.nudge_after_seconds
                and aq.nudge_count < self.max_nudges
            ):
                return True, "nudge"
            # Unanswered question remains active; NEVER bury it under a new question!
            return False, "active_question_pending"

        # ── Quiet hours check ──────────────────────────────────────────────────
        if not (self.active_hours_start <= current_hour < self.active_hours_end):
            return False, f"outside_active_hours ({current_hour}:00)"

        # ── Daily count check ──────────────────────────────────────────────────
        daily = state.get("daily_stats", {})
        if daily.get("date") == today_str and daily.get("count", 0) >= self.questions_per_day:
            return False, f"daily_limit_reached ({daily.get('count')}/{self.questions_per_day})"

        # ── Minimum gap check ──────────────────────────────────────────────────
        history = state.get("history", [])
        if history:
            last_asked_at = history[-1].get("asked_at", 0)
            if (now_ts - last_asked_at) < self.min_gap_seconds:
                return False, f"min_gap_not_met ({int((now_ts - last_asked_at)/60)}m < {int(self.min_gap_seconds/60)}m)"

        # ── Check if survey needed ─────────────────────────────────────────────
        if not state.get("queued_questions"):
            self.run_survey(force=True)
            state = self.load_state()

        if not state.get("queued_questions"):
            return False, "no_questions_available"

        return True, "ask"

    def pop_next_question(self, now_ts: Optional[float] = None) -> Optional[ActiveQuestion]:
        """Pop the next question from the queue and set it as active."""
        now_ts = now_ts or time.time()
        now_dt = datetime.fromtimestamp(now_ts)
        today_str = now_dt.strftime("%Y-%m-%d")

        state = self.load_state()
        queue = state.get("queued_questions", [])
        if not queue:
            self.run_survey(force=True)
            state = self.load_state()
            queue = state.get("queued_questions", [])

        if not queue:
            return None

        q_dict = queue.pop(0)
        q = CuriosityQuestion.from_dict(q_dict)

        active = ActiveQuestion(
            id=q.id,
            topic=q.topic,
            target_file=q.target_file,
            question=q.question,
            context=q.context,
            category=q.category,
            asked_at=now_ts,
            status="pending",
        )

        state["queued_questions"] = queue
        state["active_question"] = active.to_dict()

        # Update daily stats
        daily = state.get("daily_stats", {})
        if daily.get("date") == today_str:
            daily["count"] += 1
        else:
            daily = {"date": today_str, "count": 1}
        state["daily_stats"] = daily

        self.save_state(state)
        return active

    def register_message_sent(self, message_id: int, channel_id: str) -> None:
        """Record the Discord message ID where the question was posted."""
        state = self.load_state()
        if state.get("active_question"):
            state["active_question"]["message_id"] = message_id
            state["active_question"]["channel_id"] = channel_id
            self.save_state(state)

    def register_nudge_sent(self) -> None:
        """Record that a gentle reminder was sent."""
        state = self.load_state()
        if state.get("active_question"):
            state["active_question"]["nudge_count"] = state["active_question"].get("nudge_count", 0) + 1
            state["active_question"]["last_nudged_at"] = time.time()
            self.save_state(state)

    def classify_intent(self, user_text: str, reply_to_message_id: Optional[int] = None) -> str:
        """
        Classifies incoming user message against the active question:
        - 'skip': user wants to pass/skip this question.
        - 'answer': user answered the curiosity question.
        - 'unrelated': user asked something else; keep question pending and keep open ear.
        """
        st = self.load_state()
        aq_data = st.get("active_question")
        if not aq_data or aq_data.get("status") != "pending":
            return "unrelated"

        text = user_text.strip()
        lower = text.lower()

        # 1. Check for skip commands or phrasing
        skip_phrases = [
            "skip", "skip it", "skip this", "pass", "not now", "next", "next question",
            "/curiosity skip", "skip that", "dont ask", "don't ask", "ignore"
        ]
        if lower in skip_phrases or any(lower.startswith(p + " ") for p in ["skip", "pass"]):
            return "skip"

        # 2. Check if explicitly replying to curiosity message
        expected_msg_id = aq_data.get("message_id")
        if reply_to_message_id and expected_msg_id and reply_to_message_id == expected_msg_id:
            # Direct Discord reply to question is an answer unless it's a command
            if not text.startswith(("/", "!", "$")):
                return "answer"

        # 3. Check for obvious bot queries or administrative commands
        command_starters = (
            "/", "!", "sudo ", "docker ", "systemctl ", "git ", "ssh ", "ls ", "cat ",
            "what is ", "what's ", "how is ", "how do ", "can you ", "could you ",
            "status of ", "check ", "restart ", "deploy ", "kill ", "ping "
        )
        if any(lower.startswith(c) for c in command_starters):
            # If the command isn't specifically about the question topic, it's unrelated
            topic = aq_data.get("topic", "").lower()
            if topic and topic in lower and len(text.split()) > 4:
                return "answer"
            return "unrelated"

        # 4. Check for topic alignment or informative personal statement
        topic = aq_data.get("topic", "").lower()
        question = aq_data.get("question", "").lower()
        topic_words = set(re.findall(r"\w{3,}", f"{topic} {question}"))

        user_words = set(re.findall(r"\w{3,}", lower))
        overlap = topic_words.intersection(user_words)

        # If user provides a descriptive response (> 3 words) or has word overlap
        if len(text.split()) >= 3 and (overlap or not lower.endswith("?")):
            return "answer"

        # If it's a pure question from the user, it's unrelated
        if lower.endswith("?"):
            return "unrelated"

        return "answer"

    def record_answer(self, user_answer: str, auto_stage: bool = True) -> Tuple[ActiveQuestion, Optional[Path]]:
        """Mark active question as answered and stage insight into Dominion inbox."""
        state = self.load_state()
        aq_data = state.get("active_question")
        if not aq_data:
            raise ValueError("No active question to answer.")

        aq = ActiveQuestion.from_dict(aq_data)
        now = time.time()
        aq.user_answer = user_answer.strip()
        aq.status = "answered"
        aq.answered_at = now

        staged_path = None
        if auto_stage:
            staged_path = self.stage_insight(aq)

        # Move to history and clear active
        state["active_question"] = None
        state.setdefault("history", []).append(aq.to_dict())
        self.save_state(state)

        log.info("Recorded answer for [%s]. Staged: %s", aq.id, staged_path)
        return aq, staged_path

    def skip_active_question(self, reason: str = "user_skipped") -> Optional[ActiveQuestion]:
        """Skip current active question and clear it from active state."""
        state = self.load_state()
        aq_data = state.get("active_question")
        if not aq_data:
            return None

        aq = ActiveQuestion.from_dict(aq_data)
        aq.status = "skipped"
        aq.user_answer = f"Skipped ({reason})"
        aq.answered_at = time.time()

        state["active_question"] = None
        state.setdefault("history", []).append(aq.to_dict())
        self.save_state(state)

        log.info("Skipped active question [%s]", aq.id)
        return aq

    def stage_insight(self, aq: ActiveQuestion) -> Path:
        """Stage curiosity insight into /mnt/hdd/notes/Dominion/mind/inbox/ as pending-review."""
        today = date.today().isoformat()
        target = self.inbox_dir
        target.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"[^a-z0-9]+", "-", aq.topic.lower()).strip("-")
        existing_files = list(target.glob(f"{today}-curiosity-{slug}*.md"))
        suffix = f"-{len(existing_files)+1}" if existing_files else ""
        filename = f"{today}-curiosity-{slug}{suffix}.md"
        path = target / filename

        content = f"""---
status: pending-review
source: oracle-curiosity
topic: {aq.topic}
entity: {aq.target_file}
question_id: {aq.id}
date: {today}
---

# Curiosity learning — {aq.topic}

**Question asked:** {aq.question}  
**User response:** {aq.user_answer}  
**Origin / Context:** {aq.context}  

## Extracted Insights
- {aq.user_answer}

## Steward Action
- Review facts and promote into `{aq.target_file}` or `mind/about-me.md`.
- Close or update `## Open questions` in `{aq.target_file}` if resolved.
"""
        path.write_text(content, encoding="utf-8")
        log.info("Staged curiosity note → %s", path)
        return path

    def format_discord_question(self, q: CuriosityQuestion) -> str:
        """Format curiosity question nicely for Discord DM."""
        return (
            f"🧭 **Dominion Curiosity**\n"
            f"{q.question}\n\n"
            f"_(Reply anytime to expand the vault, or say `skip` to pass)_"
        )

    def format_discord_nudge(self, aq: ActiveQuestion) -> str:
        """Format gentle reminder for an unanswered question."""
        return (
            f"🧭 **Dominion Curiosity** _(gentle check-in)_\n"
            f"Whenever you get a breather, I was still curious:\n"
            f"> {aq.question}\n\n"
            f"_(Reply to record in Dominion, or say `skip` anytime!)_"
        )

    def get_status_summary(self) -> dict:
        """Get summary of engine status for /curiosity status command."""
        state = self.load_state()
        aq_data = state.get("active_question")
        history = state.get("history", [])
        answered_count = sum(1 for h in history if h.get("status") == "answered")
        skipped_count = sum(1 for h in history if h.get("status") == "skipped")

        return {
            "enabled": self.enabled,
            "has_active_question": bool(aq_data),
            "active_question": aq_data,
            "queue_length": len(state.get("queued_questions", [])),
            "answered_count": answered_count,
            "skipped_count": skipped_count,
            "daily_stats": state.get("daily_stats", {}),
            "last_survey_at": state.get("last_survey_at", 0),
        }

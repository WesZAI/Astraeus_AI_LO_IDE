# ==========================================
# Copyright (c) 2026 Gabriela Berger AI Oberland
# All Rights Reserved.
# This code is subject to the custom NON-COMMERCIAL 
# & ANTI-CORPORATE LICENSE (Maximum 20 PCs) found in the LICENSE file.
# ==========================================
# memory_bridge.py
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from database_manager import SQLiteMemoryManager

USER_ID = 1  # single-user app; fixed id


class MemoryBridge:
    def __init__(self, db_path: str = "memory.sqlite3"):
        self.memory_manager = SQLiteMemoryManager(db_path)
        self.memory_manager.connect()
        self.conn = self.memory_manager.conn
        self._initialize_global_patterns()

    # ------------------------------------------------------------------ #
    #  Init                                                                #
    # ------------------------------------------------------------------ #

    def _initialize_global_patterns(self):
        """Seed global_patterns with a few common phrases on first run."""
        patterns = [
            {"text": "Hello! How are you today?",  "simple_variants": ["Hi", "Hey"],           "theme": "greeting",     "intent": "social",       "sentiment": 0.8},
            {"text": "Can you help me?",            "simple_variants": ["Help"],                 "theme": "request",      "intent": "assistance",   "sentiment": 0.7},
            {"text": "Thank you!",                  "simple_variants": ["Thanks"],               "theme": "gratitude",    "intent": "appreciation", "sentiment": 1.0},
            {"text": "I don't know.",               "simple_variants": ["No idea", "Dunno"],     "theme": "uncertainty",  "intent": "admission",    "sentiment": 0.3},
            {"text": "What do you mean?",           "simple_variants": ["Explain", "Clarify"],   "theme": "clarification","intent": "understanding","sentiment": 0.5},
        ]
        cursor = self.conn.cursor()
        for p in patterns:
            cursor.execute(
                "INSERT OR IGNORE INTO global_patterns "
                "(text, simple_variants, theme, intent, sentiment, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (p["text"], json.dumps(p["simple_variants"]),
                 p["theme"], p["intent"], p["sentiment"], datetime.now().isoformat()),
            )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Pattern helpers                                                     #
    # ------------------------------------------------------------------ #

    def detect_agent_name(self, text: str) -> Optional[str]:
        for name in ["Astraeus", "Gemini", "ChatGPT", "Claude", "Copilot"]:
            if name.lower() in text.lower():
                return name
        return None

    def expand_pattern(self, user_id: int, simple_text: str) -> str:
        """Expand short text using user-specific or global patterns."""
        cursor = self.conn.cursor()

        # User-specific expansion
        cursor.execute(
            "SELECT expanded_text FROM user_patterns "
            "WHERE user_id = ? AND simple_text = ? "
            "ORDER BY confidence DESC, last_used DESC LIMIT 1",
            (user_id, simple_text),
        )
        row = cursor.fetchone()
        if row:
            return row["expanded_text"]

        # Global pattern — search inside the JSON variants array
        cursor.execute(
            "SELECT text FROM global_patterns "
            "WHERE simple_variants LIKE '%' || ? || '%' LIMIT 1",
            (simple_text,),
        )
        row = cursor.fetchone()
        return row["text"] if row else simple_text

    def learn_expansion(self, user_id: int, simple_text: str, expanded_text: str, confidence: float = 0.9):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_patterns "
            "(user_id, simple_text, expanded_text, confidence, last_used) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, simple_text, expanded_text, confidence, datetime.now().isoformat()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Storage                                                             #
    # ------------------------------------------------------------------ #

    def store_fragment(self, user_id: int, text: str, speaker: str, metadata: Dict):
        """Store one conversation fragment and record its occurrence."""
        expanded_text = self.expand_pattern(user_id, text)

        if not self._pattern_exists(expanded_text):
            self._store_global_pattern(expanded_text, metadata)

        if text != expanded_text:
            self.learn_expansion(user_id, text, expanded_text)

        self._record_occurrence(user_id, expanded_text, speaker)

    def store_exchange(self, user_text: str, ai_text: str, theme: str = "conversation"):
        """Convenience wrapper: store both sides of a user↔AI exchange."""
        meta = {"theme": theme, "intent": "chat", "sentiment": 0.5}
        self.store_fragment(USER_ID, user_text, "user", meta)
        self.store_fragment(USER_ID, ai_text,   "assistant", meta)

    def _pattern_exists(self, text: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM global_patterns WHERE text = ?", (text,))
        return cursor.fetchone() is not None

    def _store_global_pattern(self, text: str, metadata: Dict):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO global_patterns (text, theme, intent, sentiment, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (text, metadata.get("theme"), metadata.get("intent"),
             metadata.get("sentiment", 0.5), datetime.now().isoformat()),
        )
        self.conn.commit()

    def _record_occurrence(self, user_id: int, text: str, speaker: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO occurrences (user_id, pattern_id, speaker, timestamp) "
            "VALUES (?, (SELECT id FROM global_patterns WHERE text = ?), ?, ?)",
            (user_id, text, speaker, datetime.now().isoformat()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Retrieval                                                           #
    # ------------------------------------------------------------------ #

    def retrieve_conversation(self, user_id: int, start_time: datetime, end_time: datetime) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT p.text, o.speaker, o.timestamp "
            "FROM occurrences o "
            "JOIN global_patterns p ON o.pattern_id = p.id "
            "WHERE o.user_id = ? AND o.timestamp BETWEEN ? AND ? "
            "ORDER BY o.timestamp",
            (user_id, start_time.isoformat(), end_time.isoformat()),
        )
        return [dict(r) for r in cursor.fetchall()]

    def retrieve_with_scores(self, user_id: int, query_text: str, top_n: int = 5) -> List[Dict]:
        """Return the top-N stored fragments most similar to query_text."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT p.text, p.theme, p.intent, p.sentiment, o.timestamp, o.speaker "
            "FROM occurrences o "
            "JOIN global_patterns p ON o.pattern_id = p.id "
            "WHERE o.user_id = ? "
            "ORDER BY o.timestamp DESC "
            "LIMIT ?",
            (user_id, top_n * 10),   # fetch more, then re-rank by similarity
        )
        rows = cursor.fetchall()

        scored = []
        for row in rows:
            score = self._calculate_similarity(query_text, row["text"])
            scored.append({
                "text":      row["text"],
                "theme":     row["theme"],
                "intent":    row["intent"],
                "sentiment": row["sentiment"],
                "timestamp": row["timestamp"],
                "speaker":   row["speaker"],
                "score":     score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]

    def _calculate_similarity(self, query_text: str, target_text: str) -> float:
        query_words  = set(query_text.lower().split())
        target_words = set(target_text.lower().split())
        common = query_words & target_words
        return len(common) / max(1, len(query_words))

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def close(self):
        self.memory_manager.close()

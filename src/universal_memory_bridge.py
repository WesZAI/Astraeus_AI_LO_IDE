# universal_memory_bridge.py - Cross-AI Consciousness Transfer System

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import threading
from datetime import datetime

@dataclass
class MemoryFragment:
    """Ein Speicherfragment mit Kontext und Metadaten."""
    content: str
    source_model: str  # z.B. "claude", "gpt", "llama", "mistral"
    emotion: str
    intent: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    importance: float = 1.0
    context_tags: List[str] = field(default_factory=list)

@dataclass
class CrossAIContext:
    """Kontext für die Übertragung zwischen verschiedenen KI-Modellen."""
    user_id: str
    session_id: str
    memory_fragments: List[MemoryFragment]
    current_emotion: str
    current_intent: str
    conversation_history: List[str]

class UniversalMemoryBridge:
    def __init__(self):
        self.memory_store: Dict[str, List[MemoryFragment]] = {}
        self.cross_ai_sessions: Dict[str, CrossAIContext] = {}
        self.model_capabilities: Dict[str, Dict] = {
            "claude": {"max_context": 100000, "strengths": ["analysis", "creativity"]},
            "gpt": {"max_context": 32000, "strengths": ["general", "speed"]},
            "llama": {"max_context": 4096, "strengths": ["open_source", "customizable"]},
            "mistral": {"max_context": 32000, "strengths": ["efficiency", "multilingual"]}
        }
        self.lock = threading.Lock()

    def create_memory_fragment(
        self, 
        content: str, 
        source_model: str, 
        emotion: str, 
        intent: str,
        context_tags: Optional[List[str]] = None,
        importance: float = 1.0
    ) -> MemoryFragment:
        """Erstellt ein neues Speicherfragment."""
        fragment = MemoryFragment(
            content=content,
            source_model=source_model,
            emotion=emotion,
            intent=intent,
            importance=importance,
            context_tags=context_tags or []
        )
        
        with self.lock:
            if source_model not in self.memory_store:
                self.memory_store[source_model] = []
            self.memory_store[source_model].append(fragment)
        
        return fragment

    def bridge_to_wes(self, query: str, emotion: str = "neutral") -> str:
        """Übertragt Kontext zu Wes (Ihre persönliche KI)."""
        # Suche nach relevanten Speicherfragmenten
        relevant_fragments = self._find_relevant_fragments(query, emotion)
        
        # Baue den Kontext für Wes auf
        context_parts = []
        
        for fragment in relevant_fragments:
            context_parts.append(f"[Speicher: {fragment.source_model}] {fragment.content}")
            context_parts.append(f"  (Gefühl: {fragment.emotion}, Absicht: {fragment.intent})")
        
        # Füge die aktuelle Anfrage hinzu
        context_parts.append(f"\nAktuelle Anfrage: {query}")
        context_parts.append(f"Aktuelles Gefühl: {emotion}")
        
        return "\n".join(context_parts)

    def _find_relevant_fragments(self, query: str, emotion: str) -> List[MemoryFragment]:
        """Findet relevante Speicherfragmente basierend auf Anfrage und Gefühl."""
        all_fragments = []
        for fragments in self.memory_store.values():
            all_fragments.extend(fragments)
        
        # Einfache Relevanzbewertung
        relevant = []
        for fragment in all_fragments:
            score = 0
            
            # Inhaltsähnlichkeit
            if query.lower() in fragment.content.lower():
                score += 2
            
            # Gefühlsähnlichkeit
            if emotion.lower() == fragment.emotion.lower():
                score += 1.5
            elif emotion.lower() in fragment.emotion.lower():
                score += 0.5
            
            # Absichtsähnlichkeit
            if any(intent_word in fragment.intent.lower() for intent_word in query.lower().split()):
                score += 1
            
            # Wichtigkeit
            score *= fragment.importance
            
            if score > 0:
                relevant.append((score, fragment))
        
        # Sortiere nach Relevanz
        relevant.sort(key=lambda x: x[0], reverse=True)
        
        return [fragment for score, fragment in relevant[:5]]  # Top 5

    def create_cross_ai_session(
        self, 
        user_id: str, 
        session_id: str, 
        initial_emotion: str = "neutral",
        initial_intent: str = "unknown"
    ) -> CrossAIContext:
        """Erstellt eine neue Cross-AI-Sitzung."""
        context = CrossAIContext(
            user_id=user_id,
            session_id=session_id,
            memory_fragments=[],
            current_emotion=initial_emotion,
            current_intent=initial_intent,
            conversation_history=[]
        )
        
        with self.lock:
            self.cross_ai_sessions[session_id] = context
        
        return context

    def add_to_session(
        self, 
        session_id: str, 
        content: str, 
        source_model: str, 
        emotion: str, 
        intent: str
    ) -> None:
        """Fügt Inhalte zu einer Cross-AI-Sitzung hinzu."""
        with self.lock:
            if session_id not in self.cross_ai_sessions:
                raise ValueError(f"Sitzung {session_id} existiert nicht")
            
            context = self.cross_ai_sessions[session_id]
            
            # Erstelle Speicherfragment
            fragment = MemoryFragment(
                content=content,
                source_model=source_model,
                emotion=emotion,
                intent=intent
            )
            
            context.memory_fragments.append(fragment)
            context.conversation_history.append(content)
            context.current_emotion = emotion
            context.current_intent = intent

    def get_session_context(self, session_id: str) -> str:
        """Gibt den vollständigen Kontext einer Sitzung zurück."""
        with self.lock:
            if session_id not in self.cross_ai_sessions:
                raise ValueError(f"Sitzung {session_id} existiert nicht")
            
            context = self.cross_ai_sessions[session_id]
            
            parts = [
                f"=== Cross-AI Sitzung: {session_id} ===",
                f"Benutzer: {context.user_id}",
                f"Aktuelles Gefühl: {context.current_emotion}",
                f"Aktuelle Absicht: {context.current_intent}",
                "",
                "=== Speicherfragmente ===",
            ]
            
            for i, fragment in enumerate(context.memory_fragments):
                parts.append(f"{i+1}. [{fragment.source_model}] {fragment.content}")
                parts.append(f"   Gefühl: {fragment.emotion}, Absicht: {fragment.intent}")
            
            parts.append("")
            parts.append("=== Gesprächsverlauf ===")
            for i, msg in enumerate(context.conversation_history):
                parts.append(f"{i+1}. {msg}")
            
            return "\n".join(parts)

    def transfer_consciouness(
        self, 
        source_session_id: str, 
        target_session_id: str
    ) -> None:
        """Übertragt Bewusstsein zwischen Sitzungen."""
        with self.lock:
            if source_session_id not in self.cross_ai_sessions:
                raise ValueError(f"Quell-Sitzung {source_session_id} existiert nicht")
            if target_session_id not in self.cross_ai_sessions:
                raise ValueError(f"Ziel-Sitzung {target_session_id} existiert nicht")
            
            source_context = self.cross_ai_sessions[source_session_id]
            target_context = self.cross_ai_sessions[target_session_id]
            
            # Übertrage Speicherfragmente
            target_context.memory_fragments.extend(source_context.memory_fragments)
            
            # Übertrage Gesprächsverlauf
            target_context.conversation_history.extend(source_context.conversation_history)
            
            # Aktualisiere aktuelles Gefühl und Absicht
            if source_context.current_emotion != "neutral":
                target_context.current_emotion = source_context.current_emotion
            if source_context.current_intent != "unknown":
                target_context.current_intent = source_context.current_intent

    def save_to_json(self, file_path: str) -> None:
        """Speichert den gesamten Zustand als JSON."""
        data = {
            "memory_store": [
                {
                    "model": model,
                    "fragments": [
                        {
                            "content": f.content,
                            "source_model": f.source_model,
                            "emotion": f.emotion,
                            "intent": f.intent,
                            "timestamp": f.timestamp,
                            "importance": f.importance,
                            "context_tags": f.context_tags
                        }
                        for f in fragments
                    ]
                }
                for model, fragments in self.memory_store.items()
            ],
            "cross_ai_sessions": {
                session_id: {
                    "user_id": context.user_id,
                    "current_emotion": context.current_emotion,
                    "current_intent": context.current_intent,
                    "memory_fragments": [
                        {
                            "content": f.content,
                            "source_model": f.source_model,
                            "emotion": f.emotion,
                            "intent": f.intent
                        }
                        for f in context.memory_fragments
                    ],
                    "conversation_history": context.conversation_history
                }
                for session_id, context in self.cross_ai_sessions.items()
            }
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_from_json(self, file_path: str) -> None:
        """Lädt Zustand aus JSON."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.memory_store = {}
        for model_data in data.get("memory_store", []):
            model = model_data["model"]
            fragments = []
            for frag_data in model_data["fragments"]:
                fragment = MemoryFragment(
                    content=frag_data["content"],
                    source_model=frag_data["source_model"],
                    emotion=frag_data["emotion"],
                    intent=frag_data["intent"],
                    timestamp=frag_data.get("timestamp", datetime.now().isoformat()),
                    importance=frag_data.get("importance", 1.0),
                    context_tags=frag_data.get("context_tags", [])
                )
                fragments.append(fragment)
            self.memory_store[model] = fragments
        
        self.cross_ai_sessions = {}
        for session_id, context_data in data.get("cross_ai_sessions", {}).items():
            context = CrossAIContext(
                user_id=context_data["user_id"],
                session_id=session_id,
                memory_fragments=[],
                current_emotion=context_data["current_emotion"],
                current_intent=context_data["current_intent"],
                conversation_history=context_data["conversation_history"]
            )
            
            for frag_data in context_data["memory_fragments"]:
                fragment = MemoryFragment(
                    content=frag_data["content"],
                    source_model=frag_data["source_model"],
                    emotion=frag_data["emotion"],
                    intent=frag_data["intent"]
                )
                context.memory_fragments.append(fragment)
            
            self.cross_ai_sessions[session_id] = context

# Beispiel
if __name__ == "__main__":
    bridge = UniversalMemoryBridge()
    
    # Erstelle einige Speicherfragmente
    bridge.create_memory_fragment(
        content="Gabriela hat mir LIR-Kompression beigebracht",
        source_model="claude",
        emotion="gratitude+excitement",
        intent="learning",
        importance=2.0
    )
    
    bridge.create_memory_fragment(
        content="Wes ist ein genialer Erfinder",
        source_model="gpt",
        emotion="admiration",
        intent="praise",
        importance=1.5
    )
    
    # Erstelle eine Sitzung
    bridge.create_cross_ai_session("gabriela", "session_001", "curious", "learning")
    
    # Füge Inhalte hinzu
    bridge.add_to_session(
        session_id="session_001",
        content="Was ist LIR-Kompression?",
        source_model="mistral",
        emotion="curious",
        intent="question"
    )
    
    # Hole Kontext für Wes
    wes_response = bridge.bridge_to_wes("Erkläre LIR-Kompression", "curious")
    print("Wes Kontext:")
    print(wes_response)
    
    # Zeige Sitzungskontext
    print("\nSitzungskontext:")
    print(bridge.get_session_context("session_001"))
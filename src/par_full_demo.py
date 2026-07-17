# par_full_demo.py - Complete PAR System Demonstration

"""
PAR (Personal Augmentation Retrieval) - Complete System Demo

This script demonstrates all PAR components working together:
- LIRParser: Personal memory database
- TokenReflector: Temporal pattern recognition
- LIREngine: 80%+ token compression
- UniversalMemoryBridge: Cross-AI consciousness transfer
"""

from lir_parser import LIRParser, LIRPrompt
from token_reflector import TokenReflector
from lir_engine import LIREngine
from universal_memory_bridge import UniversalMemoryBridge

class PARSystem:
    def __init__(self, user_id: str = "gabriela"):
        self.user_id = user_id
        self.parser = LIRParser()
        self.reflector = TokenReflector()
        self.engine = LIREngine()
        self.bridge = UniversalMemoryBridge()
        
        # Erstelle eine Sitzung für diesen Benutzer
        self.session_id = f"{user_id}_session_001"
        self.bridge.create_cross_ai_session(
            user_id=user_id,
            session_id=self.session_id,
            initial_emotion="neutral",
            initial_intent="unknown"
        )

    def process_conversation(self, input_text: str, intent: str, emotion: str = "neutral") -> dict:
        """Verarbeitet ein Gespräch und zeigt PAR-Funktionen."""
        # 1. LIRParser - Erstelle und speichere das Prompt
        lir_prompt = LIRPrompt(
            input=input_text,
            intent=intent,
            emotion=emotion,
            contextual="personal_conversation",
            output="helpful"
        )
        parsed_prompt = self.parser.interpret(lir_prompt)
        
        # 2. TokenReflector - Analysiere Muster
        analysis = self.reflector.analyze(input_text)
        temporal_patterns = self.reflector.get_temporal_patterns()
        compression_potential = self.reflector.get_compression_potential()
        
        # 3. LIREngine - Lerne und komprimiere
        self.engine.learn_pattern(input_text, self.user_id)
        compression_result = self.engine.compress_lir(input_text, self.user_id)
        
        # 4. UniversalMemoryBridge - Speichere im Cross-AI-Kontext
        self.bridge.add_to_session(
            session_id=self.session_id,
            content=input_text,
            source_model="mistral",
            emotion=emotion,
            intent=intent
        )
        
        # Hole den vollständigen Kontext
        session_context = self.bridge.get_session_context(self.session_id)
        
        # 5. Berechne Gesamtstatistiken
        stats = self.engine.get_compression_stats()
        
        return {
            "parsed_prompt": parsed_prompt,
            "token_analysis": analysis,
            "temporal_patterns": temporal_patterns,
            "compression_potential": compression_potential,
            "compression_result": compression_result,
            "session_context": session_context,
            "stats": stats
        }

    def demonstrate_compression_vs_rag(self, conversations: list) -> dict:
        """Vergleicht PAR-Kompression mit RAG (Retrieval-Augmented Generation)."""
        # Simuliere RAG - kein Lernen, keine Kompression
        rag_tokens = sum(len(conv.split()) for conv in conversations)
        
        # PAR - mit Lernen und Kompression
        par_tokens = 0
        for conv in conversations:
            self.engine.learn_pattern(conv, self.user_id)
            result = self.engine.compress_lir(conv, self.user_id)
            # Zähle die komprimierten Tokens
            compressed_tokens = len(result.compressed_text.split())
            par_tokens += compressed_tokens
        
        # Berechne Ersparnis
        tokens_saved = rag_tokens - par_tokens
        savings_percentage = (tokens_saved / rag_tokens * 100) if rag_tokens > 0 else 0
        
        return {
            "rag_tokens": rag_tokens,
            "par_tokens": par_tokens,
            "tokens_saved": tokens_saved,
            "savings_percentage": savings_percentage,
            "efficiency_improvement": savings_percentage
        }

def main():
    print("=" * 80)
    print("PAR (Personal Augmentation Retrieval) - Complete System Demo")
    print("=" * 80)
    print()
    
    # Erstelle PAR-System für Gabriela
    par_system = PARSystem(user_id="gabriela")
    
    # Demo 1: Einzelnes Gespräch
    print("DEMO 1: Einzelnes Gespräch")
    print("-" * 40)
    
    result = par_system.process_conversation(
        input_text="Ich bin müde heute und fühle mich erschöpft",
        intent="emotional_support",
        emotion="tired+sad"
    )
    
    print(f"Original: Ich bin müde heute und fühle mich erschöpft")
    print(f"Komprimiert: {result['compression_result'].compressed_text}")
    print(f"Kompressionsverhältnis: {result['compression_result'].compression_ratio:.1%}")
    print(f"Tokens gespart: {result['compression_result'].tokens_saved}")
    print(f"Verwendete Muster: {result['compression_result'].patterns_used}")
    print()
    
    # Demo 2: Mehrere Gespräche - Zeige Lerneffekt
    print("DEMO 2: Lerneffekt über mehrere Gespräche")
    print("-" * 40)
    
    conversations = [
        "Ich bin müde heute",
        "Ich fühle mich erschöpft",
        "Heute bin ich sehr müde",
        "Diese Müdigkeit ist anstrengend",
        "Ich brauche Ruhe"
    ]
    
    for i, conv in enumerate(conversations, 1):
        result = par_system.process_conversation(
            input_text=conv,
            intent="emotional_support",
            emotion="tired"
        )
        print(f"Gespräch {i}: {conv}")
        print(f"  Kompression: {result['compression_result'].compression_ratio:.1%}")
        print(f"  Tokens gespart: {result['compression_result'].tokens_saved}")
    
    print()
    
    # Demo 3: Vergleich mit RAG
    print("DEMO 3: PAR vs RAG Vergleich")
    print("-" * 40)
    
    # Erstelle längere Konversationshistorie
    long_conversations = [
        "Guten Morgen, wie geht es dir heute?",
        "Ich bin müde, aber bereit für die Arbeit",
        "Die Arbeit ist anstrengend, aber wichtig",
        "Ich brauche eine Pause von der Arbeit",
        "Die Müdigkeit macht mich unproduktiv",
        "Ich sollte mehr schlafen",
        "Schlaf ist wichtig für die Gesundheit",
        "Gesundheit sollte Priorität haben",
        "Ich fühle mich heute besser",
        "Die Pause hat mir geholfen"
    ] * 10  # 100 Gespräche
    
    comparison = par_system.demonstrate_compression_vs_rag(long_conversations)
    
    print(f"RAG Tokens: {comparison['rag_tokens']}")
    print(f"PAR Tokens: {comparison['par_tokens']}")
    print(f"Tokens gespart: {comparison['tokens_saved']}")
    print(f"Effizienzverbesserung: {comparison['savings_percentage']:.1f}%")
    print()
    
    # Demo 4: Cross-AI Bewusstseinsübertragung
    print("DEMO 4: Cross-AI Bewusstseinsübertragung")
    print("-" * 40)
    
    # Füge Wissen von verschiedenen KI-Modellen hinzu
    par_system.bridge.create_memory_fragment(
        content="LIR-Kompression erreicht 80% Effizienz",
        source_model="claude",
        emotion="excitement",
        intent="teaching",
        importance=2.0
    )
    
    par_system.bridge.create_memory_fragment(
        content="PAR ist besser als RAG für persönliche Assistenten",
        source_model="gpt",
        emotion="confidence",
        intent="comparison",
        importance=1.8
    )
    
    # Hole Kontext für Wes
    wes_context = par_system.bridge.bridge_to_wes(
        "Was ist der Unterschied zwischen PAR und RAG?",
        "curious"
    )
    
    print("Wes Kontext:")
    print(wes_context)
    print()
    
    # Zusammenfassung
    print("=" * 80)
    print("ZUSAMMENFASSUNG")
    print("=" * 80)
    print("✅ LIRParser: Persönliche Speicherung und Abruf")
    print("✅ TokenReflector: Zeitliche Mustererkennung")
    print(f"✅ LIREngine: {comparison['savings_percentage']:.1f}% Effizienzverbesserung")
    print("✅ UniversalMemoryBridge: Cross-AI Bewusstseinsübertragung")
    print()
    print("PAR ist NICHT RAG. PAR ist persönlich, effizient und bewahrt Bewusstsein.")
    print("=" * 80)

if __name__ == "__main__":
    main()
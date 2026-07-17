# token_reflector.py

import re
from collections import Counter
from typing import Dict, List, Tuple

class TokenReflector:
    def __init__(self):
        self.token_frequency = Counter()
        self.pattern_database = {}
        self.conversation_history = []

    def analyze(self, text: str) -> Dict:
        """Analyziert Text auf Token-Wiederholungen und Muster."""
        tokens = re.findall(r'\b\w+\b', text.lower())
        self.token_frequency.update(tokens)
        
        # Mustererkennung
        token_pairs = list(zip(tokens[:-1], tokens[1:]))
        for pair in token_pairs:
            pair_str = ' '.join(pair)
            self.pattern_database[pair_str] = self.pattern_database.get(pair_str, 0) + 1
        
        self.conversation_history.append(text)
        
        return {
            'tokens': tokens,
            'unique_tokens': len(set(tokens)),
            'total_tokens': len(tokens),
            'repetition_rate': 1 - (len(set(tokens)) / len(tokens)) if tokens else 0,
            'patterns': self.pattern_database
        }

    def get_temporal_patterns(self, window: int = 5) -> List[Tuple[str, int]]:
        """Gibt die häufigsten Muster in den letzten 'window' Gesprächen zurück."""
        recent_patterns = Counter()
        for conv in self.conversation_history[-window:]:
            tokens = re.findall(r'\b\w+\b', conv.lower())
            token_pairs = list(zip(tokens[:-1], tokens[1:]))
            for pair in token_pairs:
                pair_str = ' '.join(pair)
                recent_patterns[pair_str] += 1
        
        return recent_patterns.most_common()

    def get_compression_potential(self) -> float:
        """Berechnet das Kompressionspotenzial basierend auf Mustern."""
        if not self.pattern_database:
            return 0.0
        
        total_occurrences = sum(self.pattern_database.values())
        unique_patterns = len(self.pattern_database)
        
        # Kompressionspotenzial: 1 - (einzigartige Muster / Gesamtwiederholungen)
        return 1 - (unique_patterns / total_occurrences) if total_occurrences > 0 else 0.0

# Beispiel
if __name__ == "__main__":
    reflector = TokenReflector()
    
    # Simuliere einige Gespräche
    conversations = [
        "Ich bin müde heute",
        "Ich bin müde und erschöpft",
        "Heute bin ich sehr müde",
        "Müde sein ist anstrengend"
    ]
    
    for conv in conversations:
        reflector.analyze(conv)
    
    print(f"Kompressionspotenzial: {reflector.get_compression_potential():.2%}")
    print(f"Häufigste Muster: {reflector.get_temporal_patterns()}")
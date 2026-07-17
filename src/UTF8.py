# UTF8.py - Next-generation character encoding optimization

class UTF8Optimizer:
    def __init__(self):
        self.character_map = {}
        self.frequency_counter = {}

    def optimize_encoding(self, text: str) -> str:
        """Optimiert die Textkodierung für häufig verwendete Zeichen."""
        # Zähle Zeichenhäufigkeit
        for char in text:
            self.frequency_counter[char] = self.frequency_counter.get(char, 0) + 1
        
        # Erstelle optimierte Zuordnung
        sorted_chars = sorted(self.frequency_counter.keys(), 
                             key=lambda x: self.frequency_counter[x], 
                             reverse=True)
        
        for i, char in enumerate(sorted_chars):
            self.character_map[char] = i
        
        return text

    def get_optimization_ratio(self) -> float:
        """Berechnet das Optimierungsverhältnis."""
        if not self.frequency_counter:
            return 0.0
        
        total_chars = sum(self.frequency_counter.values())
        unique_chars = len(self.frequency_counter)
        
        # Optimierungsverhältnis
        return 1 - (unique_chars / total_chars) if total_chars > 0 else 0.0

# Beispiel
if __name__ == "__main__":
    optimizer = UTF8Optimizer()
    text = "Hallo Welt! Dies ist ein Testtext mit vielen wiederholten Zeichen."
    optimized = optimizer.optimize_encoding(text)
    print(f"Optimierungsverhältnis: {optimizer.get_optimization_ratio():.2%}")
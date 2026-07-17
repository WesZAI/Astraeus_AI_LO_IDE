# PAR: Personal Augmentation Retrieval
# Core package for the PAR system

__version__ = "1.0.0"
__author__ = "Gabriela Berger"
__description__ = "Personal Augmentation Retrieval - The original AI companion system"

from .lir_parser import LIRParser, LIRPrompt
from .token_reflector import TokenReflector
from .lir_engine import LIREngine, CompressionResult
from .universal_memory_bridge import UniversalMemoryBridge, MemoryFragment, CrossAIContext

__all__ = [
    'LIRParser',
    'LIRPrompt', 
    'TokenReflector',
    'LIREngine',
    'CompressionResult',
    'UniversalMemoryBridge',
    'MemoryFragment',
    'CrossAIContext'
]
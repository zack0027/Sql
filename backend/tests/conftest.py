"""Conftest común; agrega el src al path para que pytest encuentre el package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

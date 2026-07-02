"""
Catálogo curado de FIIs para sugestão por perfil de risco.

A lista vive em app/data/fiis.json — editável sem tocar em código Python.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

_DATA_FILE = Path(__file__).parent.parent / "data" / "fiis.json"

_TIPO_LABEL = {
    "papel": "Papel (CRI/CRA)",
    "tijolo": "Tijolo",
    "fof": "Fundo de Fundos",
}

_PROFILE_ALIASES = {
    "conservador": "conservador",
    "moderado": "moderado",
    "arrojado": "arrojado",
}


@dataclass(frozen=True)
class FII:
    ticker: str
    nome: str
    tipo: str

    @property
    def tipo_label(self) -> str:
        return _TIPO_LABEL.get(self.tipo, self.tipo)


def _eligible(data: list[dict], risk_profile: str) -> list[dict]:
    profile = _PROFILE_ALIASES.get((risk_profile or "").lower(), "conservador")
    return [d for d in data if profile in d.get("perfis", [])]


def suggest_fiis(risk_profile: str, n: int = 3) -> list[FII]:
    """Return n randomly sampled FIIs compatible with the given risk profile."""
    with _DATA_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)

    eligible = _eligible(raw, risk_profile)
    if not eligible:
        eligible = raw

    sample = random.sample(eligible, min(n, len(eligible)))
    return [FII(ticker=d["ticker"], nome=d["nome"], tipo=d["tipo"]) for d in sample]

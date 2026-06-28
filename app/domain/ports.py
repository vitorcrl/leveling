# Este módulo define as "portas" da arquitetura limpa do pipeline de ativos.
# Cada porta é um Protocol do Python — funciona como uma interface: qualquer classe
# que implemente os métodos corretos é automaticamente considerada compatível,
# sem precisar herdar de nada. Isso permite trocar implementações (ex: BrapiAdapter
# por YahooFinanceAdapter) sem mudar uma linha do pipeline.

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

# TYPE_CHECKING é True apenas durante análise estática (mypy, pyright).
# Em runtime vale False, então as importações abaixo nunca executam —
# isso evita importação circular entre ports.py e models_asset.py.
if TYPE_CHECKING:
    from app.domain.models_asset import Alert, AssetSnapshot, DigestContext


# runtime_checkable permite usar isinstance(obj, DataPort) nos testes
# para verificar se um adapter implementa a porta corretamente.


@runtime_checkable
class DataPort(Protocol):
    """De onde vêm os dados de mercado de cada ativo (cotação, DY, P/VP etc.)."""

    async def fetch(self, ticker: str) -> "AssetSnapshot":
        # Recebe o código do fundo (ex: "KNCR11") e devolve um snapshot
        # com todos os indicadores do dia. É async pois faz chamada HTTP.
        ...


@runtime_checkable
class RulePort(Protocol):
    """Onde vivem as regras de análise — DY baixo, P/VP alto, vacância elevada etc."""

    def evaluate(self, snapshot: "AssetSnapshot") -> list["Alert"]:
        # Recebe o snapshot do dia e devolve a lista de alertas disparados.
        # Síncrono: é só matemática, sem I/O.
        ...


@runtime_checkable
class ScorePort(Protocol):
    """Como calcular o score de oportunidade de compra (0–100) para cada ativo."""

    def score(self, snapshot: "AssetSnapshot") -> int:
        # Score mais alto = oportunidade melhor. Usado pelo motor de alocação
        # para distribuir o orçamento semanal proporcionalmente.
        ...


@runtime_checkable
class NarratorPort(Protocol):
    """Quem redige o texto do digest — pode ser Claude Haiku ou uma mensagem silenciosa."""

    async def narrate(self, context: "DigestContext") -> str:
        # Se não há alertas, SilentNarrator retorna uma mensagem padrão sem
        # consumir tokens. Se há alertas, ClaudeHaikuNarrator chama a API.
        ...


@runtime_checkable
class DeliveryPort(Protocol):
    """Onde o digest é entregue — Telegram, webhook, email etc."""

    async def send(self, message: str, chat_id: int | str) -> None:
        # Recebe o texto final e o destinatário. É async pois faz HTTP.
        ...

# Objetos de valor internos ao pipeline — não são tabelas do banco.
# Usamos dataclasses puras (sem SQLAlchemy) porque esses dados vivem só
# em memória durante a execução do pipeline. O ORM fica em models_fii.py.
#
# AssetSnapshot é intencionalmente "gordo": carrega campos de FIIs, REITs
# e ações no mesmo dataclass. Campos irrelevantes para um tipo de ativo
# ficam como None — o RulePort de cada tipo simplesmente os ignora.
# Isso mantém o pipeline genérico sem precisar de subclasses.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class AlertSeverity(str, Enum):
    """Gravidade de um alerta — usada pelo narrator para formatar a mensagem."""

    info = "info"          # evento neutro, ex: provento anunciado
    warning = "warning"    # indicador fora do threshold, mas não crítico
    critical = "critical"  # situação que merece atenção imediata (ex: queda >5%)


@dataclass
class Alert:
    """
    Representa um alerta disparado por uma regra para um ativo específico.
    O narrator só recebe objetos Alert — nunca o snapshot bruto inteiro,
    para manter o contexto enviado à Claude o menor possível.
    """

    ticker: str            # código do fundo/ação, ex: "MXRF11" ou "PETR4"
    rule: str              # nome da regra que disparou, ex: "dy_falling"
    message: str           # mensagem legível, ex: "DY caindo: 10,2% (era 11,5%)"
    severity: AlertSeverity = AlertSeverity.warning
    value: float | None = None      # valor atual do indicador
    threshold: float | None = None  # limite configurado que foi violado
    # Quantas semanas consecutivas essa regra está disparando para este ticker.
    # Calculado por fii_repository.count_streak() antes de montar o DigestContext.
    # O narrator usa esse número diretamente: "LTV acima do limite há 3 semanas".
    # Nunca é salvo no banco — é uma agregação calculada, não um dado.
    streak: int = 1


@dataclass
class AssetSnapshot:
    """
    Fotografia dos indicadores de um ativo em uma data específica.
    Produzido pelo DataPort (ex: BrapiDataAdapter, YahooFinanceAdapter)
    e consumido pelo RulePort e ScorePort.

    Os campos são organizados em grupos:
      - Obrigatórios: presentes em qualquer tipo de ativo
      - FIIs BR: vacancia, ltv, delta_vacancia
      - REITs US: ffo_per_share, price_ffo, debt_ebitda, occupancy, payout_ratio
      - Ações: eps, book_value_per_share, roe, ev_ebitda, revenue_growth,
               net_margin, debt_equity, beta
      - Deltas: calculados pelo pipeline comparando com snapshot anterior
    """

    # --- Campos obrigatórios (todo tipo de ativo) ---
    ticker: str    # código do ativo, ex: "KNCR11", "PLD", "PETR4"
    market: str    # mercado de origem: "BR" para FIIs/ações BR, "US" para REITs
    date: date     # data de referência do snapshot
    price: float   # cotação de fechamento

    # --- Indicadores comuns (FIIs + REITs) ---
    dy_12m: float         # dividend yield dos últimos 12 meses em %
    pvp: float            # preço dividido pelo valor patrimonial (P/VP)
    liquidez: float       # volume médio diário negociado (R$ ou USD)

    # --- Campos específicos de FIIs BR ---
    # None para REITs e ações — as regras checam antes de usar
    vacancia: float | None = None    # % de área desocupada (fundos tijolo)
    ltv: float | None = None         # loan-to-value em % (fundos papel)

    # --- Campos específicos de REITs US ---
    ffo_per_share: float | None = None   # funds from operations por cota
    price_ffo: float | None = None       # price / FFO (equivalente ao P/L para REITs)
    debt_ebitda: float | None = None     # dívida líquida / EBITDA (alavancagem)
    occupancy: float | None = None       # taxa de ocupação em % (90%+ é saudável)

    # --- Campos específicos de ações (BR e US) ---
    eps: float | None = None                   # lucro por ação (LPA)
    book_value_per_share: float | None = None  # valor patrimonial por ação (VPA)
    roe: float | None = None                   # return on equity em %
    ev_ebitda: float | None = None             # enterprise value / EBITDA
    revenue_growth: float | None = None        # crescimento de receita YoY em %
    net_margin: float | None = None            # margem líquida em %
    debt_equity: float | None = None           # dívida total / patrimônio líquido
    beta: float | None = None                  # volatilidade relativa ao índice (1.0 = neutro)
    payout_ratio: float | None = None          # % do lucro distribuído como dividendo

    # --- Deltas calculados pelo pipeline (vs semana/dia anterior) ---
    # O pipeline busca o snapshot anterior no banco e preenche esses campos
    # antes de passar para o RulePort — as regras não fazem queries.
    delta_dy: float = 0.0          # variação do DY em pontos percentuais
    delta_vacancia: float = 0.0    # variação da vacância em pontos percentuais
    delta_price: float = 0.0       # variação percentual do preço em 1 dia
    delta_pvp: float = 0.0         # variação do P/VP vs semana anterior
    delta_occupancy: float = 0.0   # variação da ocupação vs semana anterior (REITs)
    delta_ltv: float = 0.0         # variação do LTV vs semana anterior (fundos papel)

    # --- Evento pontual ---
    # None se nenhum provento/dividendo foi anunciado neste dia
    provento_anunciado: float | None = None  # valor em R$/USD por cota


@dataclass
class DigestContext:
    """
    Tudo que o NarratorPort precisa para redigir o digest do dia.
    O pipeline monta este objeto após coletar snapshots, calcular deltas,
    aplicar regras e calcular scores — aí passa para o narrator.

    O narrator recebe o contexto completo mas deve usar só o que for
    relevante para o texto — não despeja tudo na prompt da Claude.
    """

    date: date                        # data do digest
    snapshots: list[AssetSnapshot]    # todos os ativos da watchlist
    alerts: list[Alert]               # apenas os alertas disparados hoje
    scores: dict[str, int] = field(default_factory=dict)  # ticker → score 0–100

    @property
    def watchlist_size(self) -> int:
        """Total de ativos monitorados — derivado de snapshots, nunca desincroniza."""
        return len(self.snapshots)

    @property
    def total_alerts(self) -> int:
        """Total de alertas com severity warning ou critical."""
        return sum(1 for a in self.alerts if a.severity != AlertSeverity.info)

    @property
    def total_events(self) -> int:
        """Eventos informativos — proventos anunciados e outros severity=info."""
        return sum(1 for a in self.alerts if a.severity == AlertSeverity.info)

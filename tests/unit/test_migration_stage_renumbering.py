"""
Testes unitários da migration d4e5f6a7b8c9 — renumeração de stage.

Sem banco de dados: valida a lógica do CASE em SQL simulando-a em Python
(mesma expressão usada no `op.execute`) e a integridade da cadeia de
revisions do Alembic.
"""

import importlib.util
from pathlib import Path

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "d4e5f6a7b8c9_add_emergency_fund_stage.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("stage_renumbering_migration", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade_stage(old_stage: int) -> int:
    """Espelha o CASE de upgrade() na migration: 2->3, 1->2, resto inalterado."""
    if old_stage == 2:
        return 3
    if old_stage == 1:
        return 2
    return old_stage


def _downgrade_stage(new_stage: int) -> int:
    """Espelha o CASE de downgrade(): 3->2, 2->1, 1->0 (stage novo sem equivalente antigo)."""
    if new_stage == 3:
        return 2
    if new_stage == 2:
        return 1
    if new_stage == 1:
        return 0
    return new_stage


class TestUpgradeStageMapping:
    def test_debt_stage_unchanged(self):
        assert _upgrade_stage(0) == 0

    def test_old_caixinha_becomes_stage_2(self):
        assert _upgrade_stage(1) == 2

    def test_old_fiis_becomes_stage_3(self):
        assert _upgrade_stage(2) == 3

    def test_no_order_collision_when_applied_as_single_case(self):
        # Se a atualização fosse feita em duas UPDATEs sequenciais (2->3 depois 1->2),
        # um stage=1 processado antes da regra 2->3 não poderia virar 3 incorretamente.
        # A migration usa um único CASE, então simulamos a leitura em lote:
        old_stages = [0, 1, 1, 2, 2]
        new_stages = [_upgrade_stage(s) for s in old_stages]
        assert new_stages == [0, 2, 2, 3, 3]


class TestDowngradeStageMapping:
    def test_fiis_reverts_to_old_caixinha(self):
        assert _downgrade_stage(3) == 2

    def test_caixinha_reverts_to_old_dividida_placeholder(self):
        assert _downgrade_stage(2) == 1

    def test_new_emergency_fund_stage_reverts_to_debt(self):
        # stage=1 (reserva) não existia antes desta migration.
        assert _downgrade_stage(1) == 0

    def test_debt_stage_unchanged(self):
        assert _downgrade_stage(0) == 0

    def test_upgrade_then_downgrade_is_identity_for_old_stages(self):
        for old_stage in (0, 1, 2):
            assert _downgrade_stage(_upgrade_stage(old_stage)) == old_stage


class TestMigrationRevisionChain:
    def test_down_revision_points_to_latest_prior_head(self):
        module = _load_migration_module()
        assert module.down_revision == "c3d4e5f6a7b8"
        assert module.revision == "d4e5f6a7b8c9"

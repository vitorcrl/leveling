"""
Teste unitário da migration e5f6a7b8c9d0 — digest_weekday, onboarding_events,
user_profile_summary. Migration puramente aditiva, sem transformação de dados.
"""

import importlib.util
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "e5f6a7b8c9d0_digest_weekday_events_profile.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("digest_events_profile_migration", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationRevisionChain:
    def test_down_revision_points_to_emergency_fund_migration(self):
        module = _load_migration_module()
        assert module.down_revision == "d4e5f6a7b8c9"
        assert module.revision == "e5f6a7b8c9d0"


class TestUpgradeDowngradeSymmetry:
    def test_upgrade_and_downgrade_are_defined(self):
        module = _load_migration_module()
        assert callable(module.upgrade)
        assert callable(module.downgrade)

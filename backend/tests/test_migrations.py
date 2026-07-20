from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_revision_ids_fit_default_alembic_version_column() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(backend_root / "alembic.ini")
    config.set_main_option("script_location", str(backend_root / "alembic"))
    revisions = ScriptDirectory.from_config(config).walk_revisions()

    assert all(len(revision.revision) <= 32 for revision in revisions)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def test_run_experiment_rejects_external_database_injection():
    from scripts.experiment_route_glo_export import run_experiment

    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as external_session:
            with pytest.raises(TypeError, match="unexpected keyword argument 'db'"):
                run_experiment(db=external_session)

        with pytest.raises(TypeError, match="unexpected keyword argument 'database_url'"):
            run_experiment(database_url="postgresql://production.invalid/velo")
    finally:
        engine.dispose()


def test_experiment_database_is_always_script_owned_memory_database(monkeypatch):
    from scripts.experiment_route_glo_export import _experiment_db_session

    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/velo")

    with _experiment_db_session() as session:
        bind = session.get_bind()
        assert bind.dialect.name == "sqlite"
        assert str(bind.url) == "sqlite:///:memory:"


def test_internal_runner_rejects_unmarked_external_memory_session():
    from scripts.experiment_route_glo_export import _run_experiment_with_db

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    try:
        with Session(engine) as external_session:
            with pytest.raises(RuntimeError, match="script-owned SQLite in-memory session"):
                _run_experiment_with_db(
                    external_session,
                    count=1,
                    seed=20260630,
                    points_per_route=2,
                    query_func=lambda coords: [700.0 for _coord in coords],
                )
    finally:
        engine.dispose()

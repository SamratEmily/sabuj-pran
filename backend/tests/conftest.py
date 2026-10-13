from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, make_engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import Permission, Role, User
from app.modules.auth.service import sync_permissions
from app.seed import seed

TEST_PASSWORD = "Passw0rd!"

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _server_engine(url: str) -> tuple[Engine, str]:
    parsed = make_url(url)
    name = parsed.database
    assert name and name.endswith("_test"), f"Refusing to touch non-test database {name!r}"
    return create_engine(parsed.set(database=""), isolation_level="AUTOCOMMIT"), name


def recreate_database(url: str) -> None:
    """Drop and recreate a *_test database so a run starts from an empty schema."""
    server, name = _server_engine(url)
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        conn.execute(
            text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
    server.dispose()


def drop_database(url: str) -> None:
    server, name = _server_engine(url)
    with server.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
    server.dispose()


def migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    settings.bcrypt_rounds = 4  # fast hashing in tests
    settings.jwt_secret = "test-secret-at-least-32-characters-long"
    url = settings.test_database_url
    recreate_database(url)
    migrate(url)

    eng = make_engine(url)
    # Permissions are static reference data: sync once and keep for the whole run.
    with Session(eng) as session:
        sync_permissions(session)
        session.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is rolled back after each test.

    Code under test may call commit(); with create_savepoint it only releases a savepoint.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    # Not used as a context manager, so the startup permission sync (which uses the
    # real SessionLocal) does not run against the dev database.
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


MakeUser = Callable[..., User]


@pytest.fixture
def make_user(db: Session) -> MakeUser:
    """Create a user with its own role holding exactly `permissions`."""
    counter = 0

    def _make(
        username: str | None = None,
        permissions: list[str] | None = None,
        password: str = TEST_PASSWORD,
        **fields: object,
    ) -> User:
        nonlocal counter
        counter += 1
        username = username or f"user{counter}"
        role = Role(name=f"role-{username}", description="test role")
        if permissions:
            role.permissions = list(
                db.scalars(select(Permission).where(Permission.code.in_(permissions)))
            )
        user = User(
            username=username,
            full_name=f"Test {username}",
            password_hash=hash_password(password),
            role=role,
            **fields,
        )
        db.add(user)
        db.flush()
        return user

    return _make


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def admin(db: Session) -> User:
    """Full demo data (roles, users, master data) inside the test transaction; returns admin."""
    seed(db)
    user = db.scalar(select(User).where(User.username == "admin"))
    assert user is not None
    return user

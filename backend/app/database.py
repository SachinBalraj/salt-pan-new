import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_schema(engine: Engine = engine) -> None:
    """Idempotently add columns introduced after a table was first created.

    `Base.metadata.create_all` only creates missing *tables*; it never alters
    existing ones. This dev-friendly sync walks every mapped table and issues
    `ALTER TABLE ... ADD COLUMN` for newly-declared columns so an existing
    database picks up schema changes without dropping data.
    """
    insp = sa.inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        with engine.begin() as conn:
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = _column_ddl(col)
                conn.execute(
                    sa.text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}')
                )


def _column_ddl(col: sa.Column) -> str:
    typ = col.type.compile(engine.dialect)
    parts = [col.name, typ]
    if col.nullable is False:
        parts.append("NOT NULL")
    default = getattr(col, "default", None)
    if default is not None and default.is_scalar and default.arg is not None:
        val = default.arg
        if isinstance(val, bool):
            val = 1 if val else 0
        if isinstance(val, str):
            parts.append(f"DEFAULT '{val}'")
        else:
            parts.append(f"DEFAULT {val}")
    return " ".join(parts)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType):
    """Minimal pgvector SQLAlchemy type used without adding a hard dependency.

    The migration creates the real PostgreSQL `vector` column. This type lets
    models compile and lets repositories bind vectors as pgvector literals.
    """

    cache_ok = True

    def __init__(self, dimension: int | None = None) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw: Any) -> str:
        if self.dimension is None:
            return "VECTOR"
        return f"VECTOR({self.dimension})"

    def bind_processor(self, dialect):
        def process(value: Any) -> str | None:
            if value is None:
                return None
            values = list(value)
            if self.dimension is not None and len(values) != self.dimension:
                raise ValueError(
                    f"Embedding vector dimension mismatch: expected {self.dimension}, got {len(values)}."
                )
            return _to_pgvector_literal(values)

        return process

    def result_processor(self, dialect, coltype):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            if isinstance(value, str):
                stripped = value.strip().strip("[]")
                if not stripped:
                    return []
                return [float(item) for item in stripped.split(",")]
            return value

        return process


def _to_pgvector_literal(values: Iterable[Any]) -> str:
    return "[" + ",".join(str(float(item)) for item in values) + "]"

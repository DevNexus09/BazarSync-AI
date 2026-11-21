"""Read pinned, bounded artifacts from an operator-controlled directory."""

from hashlib import sha256
from hmac import compare_digest
import os
from pathlib import Path
from stat import S_ISREG
from uuid import UUID

from app.schemas.forecast_inference import ForecastModelRegistry

MIB = 1024 * 1024


def verified_file(root: Path, parts: tuple[str, ...], digest: str, limit: int) -> bytes:
    if (
        not root.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts)
    ):
        raise ValueError("Artifact paths must stay within the configured root.")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(parts[-1], flags, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError("Artifact file type or size rejected.")
            data = handle.read(limit + 1)
        if len(data) > limit or not compare_digest(sha256(data).hexdigest(), digest):
            raise ValueError("Artifact size or digest rejected.")
        return data
    finally:
        os.close(directory)


def load_registry(root: Path, seller_id: UUID, digest: str) -> ForecastModelRegistry:
    registry = ForecastModelRegistry.model_validate_json(
        verified_file(root, (str(seller_id), "registry.json"), digest, MIB)
    )
    if registry.seller_id != seller_id:
        raise PermissionError("Forecast registry outside authorized seller scope.")
    return registry

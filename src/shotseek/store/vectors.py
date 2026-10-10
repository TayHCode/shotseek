import os
import numpy as np
from ..errors import AppError
from ..paths import writable


def vector_path(index, generation):
    return index / f"vectors-{generation:06d}.f16"


def truncate(path, rows, dim, libraries=()):
    path = writable(path, libraries)
    expected = rows * dim * 2
    if path.exists() and path.stat().st_size < expected or not path.exists() and expected:
        raise AppError("index_corrupt", "The vector file is shorter than committed metadata.",
            exit_code=3)
    with path.open("r+b" if path.exists() else "w+b") as stream:
        stream.truncate(expected)


def append(path, rows, dim, data, libraries=()):
    data = np.asarray(data, dtype="<f2").reshape((-1, dim))
    if not np.isfinite(data).all():
        raise AppError("index_corrupt", "Vectors must be finite.", exit_code=3)
    path = writable(path, libraries)
    with path.open("r+b" if path.exists() else "w+b") as stream:
        stream.seek(rows * dim * 2)
        stream.write(data.tobytes())
        stream.flush()
        os.fsync(stream.fileno())
    return rows + len(data)


def read(path, rows, dim):
    if not rows:
        return np.empty((0, dim), dtype="<f2")
    if path.stat().st_size < rows * dim * 2:
        raise AppError("index_corrupt", "The vector file is truncated.", exit_code=3)
    return np.memmap(path, dtype="<f2", mode="r", shape=(rows, dim))

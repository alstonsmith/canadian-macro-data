"""Small file helper shared by the raw-file and quarantine writers."""

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp file in the same folder, so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

"""Path-safety guard for the two places this codebase ever recursively
deletes a directory tree: ``config/gunicorn_conf.py::on_starting`` and
``config/celery_metrics.py::_setup_multiproc_dir`` (Phase 11 Block 5,
sections 23-24).

Both call ``shutil.rmtree(multiproc_dir, ignore_errors=True)`` on a path
that ultimately comes from an environment variable
(``PROMETHEUS_MULTIPROC_DIR`` / ``OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR``)
— a single deployment typo (an empty value resolving to cwd, a stray ``/``,
a drive root, a path that happens to equal the checkout or the home
directory) must never turn a routine metrics-directory refresh into
irrecoverable data loss. This module is the one shared place that decides
whether a path is safe to wipe; deliberately conservative and deliberately
small (no attempt at a general filesystem sandbox) — it rejects only the
small set of catastrophically wrong targets, never second-guesses a
legitimate, sufficiently-nested application path.
"""

from __future__ import annotations

from pathlib import Path

#: Deliberately conservative: a directory this shallow is never a
#: purpose-built multiprocess scratch directory in any real deployment of
#: this application — ``/tmp/supportpilot-prometheus-multiproc`` (the
#: shipped default) has 2 segments below its anchor; requiring at least 2
#: rejects the anchor itself, a single top-level directory (``/tmp``,
#: ``C:\Temp``), and every case explicitly called out in section 24
#: (filesystem root, a drive root, cwd/repo root when it is shallow, a home
#: directory that is itself shallow) without needing to special-case any of
#: them individually.
_MINIMUM_SEGMENTS_BELOW_ANCHOR = 2


class UnsafeMultiprocessDirError(ValueError):
    """Raised when a configured Prometheus multiprocess directory is too
    dangerous to recursively delete and recreate."""


def is_safe_multiprocess_dir(path: str | Path) -> bool:
    """``True`` only for a path this codebase considers safe to
    ``shutil.rmtree()`` and recreate. Never raises — a path that cannot even
    be resolved (empty string, null byte, some other OS-level rejection) is
    itself unsafe, not an error to propagate here."""
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False

    anchor = Path(resolved.anchor) if resolved.anchor else resolved
    if resolved == anchor:
        # Filesystem root ("/") or a drive root ("C:\\") — never safe.
        return False

    try:
        relative_parts = resolved.relative_to(anchor).parts
    except ValueError:  # pragma: no cover - defensive, anchor always a prefix
        return False
    if len(relative_parts) < _MINIMUM_SEGMENTS_BELOW_ANCHOR:
        return False

    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):  # pragma: no cover - no home dir available
        home = None
    if home is not None and resolved == home:
        return False

    try:
        cwd = Path.cwd().resolve()
    except OSError:  # pragma: no cover - defensive
        cwd = None
    if cwd is not None and resolved == cwd:
        # Catches both an explicit "current working directory" value and an
        # unset/empty env var, which ``Path("").resolve()`` silently
        # defaults to cwd for — exactly the kind of typo section 24 warns
        # about, and in a container cwd is very often the application
        # checkout itself.
        return False

    # A directory recognizable as this application's own checkout root
    # (regardless of how deeply nested it happens to be on a given
    # filesystem — the segment-count check above alone would miss a
    # legitimately deep repo path) is never a valid multiprocess scratch
    # directory.
    if (resolved / "manage.py").exists() or (resolved / ".git").exists():
        return False

    # A resolved path with no parent segments left to walk up (defensive —
    # already covered by the anchor check above on every platform this runs
    # on, kept as a second, independent guard rather than trusted alone).
    if resolved.parent == resolved:  # pragma: no cover - defensive
        return False

    return True


def assert_safe_multiprocess_dir(path: str | Path) -> Path:
    """Returns the resolved path when safe; raises
    :class:`UnsafeMultiprocessDirError` otherwise. Callers use this
    immediately before ``shutil.rmtree`` — never after."""
    if not is_safe_multiprocess_dir(path):
        raise UnsafeMultiprocessDirError(
            f"Refusing to recursively delete {path!r}: not a safe Prometheus "
            "multiprocess directory (too shallow, a filesystem/drive root, "
            "or a home directory). Configure a dedicated, sufficiently "
            "nested path instead."
        )
    return Path(path).resolve()

"""Build identity — who-am-I as a build, for cache keying under a freeze.

The output cache (``report.py``) keys freshness partly on the code that produces
the output. In a dev checkout that's done by hashing the relevant ``.py`` source
files, which gives fine-grained invalidation: edit ``ingest.py`` and dependent
artifacts rebuild. A frozen one-file build has no ``.py`` on disk, so that source
hash is impossible there. The frozen substitute is a *build identity*: a string
that is stable within one build and differs between builds whose code differs.

Identity is ``version`` plus a *build stamp*. Version alone is not enough — two
nightly one-file builds can share version ``0.1.0`` yet carry different code, and
keying on the version alone would let the second build read the first's stale
cache. The stamp (a git SHA or a build timestamp, baked at freeze time) breaks
that collision. The stamp is optional and defaults to ``"dev"``; it only has to
be set for frozen builds, where the build process bakes ``_BUILD_STAMP``.
"""

from __future__ import annotations

from . import __version__


def _read_build_stamp() -> str:
    """The stamp baked into a build, or ``"dev"`` when none is.

    The build step writes a tiny ``_build_stamp.py`` next to this module holding
    ``STAMP = "<git-sha-or-timestamp>"`` and bundles it into the freeze (see
    ``tn.spec`` / ``scripts/stamp_build.py`` and ``docs/PACKAGING.md``). That file
    is generated, git-ignored, and absent in a clean checkout — so importing it
    may fail, and the dev fallback is ``"dev"``. We resolve once at import: the
    stamp is fixed for a build's lifetime, and re-importing per call would add
    nothing.
    """
    try:
        from ._build_stamp import STAMP  # type: ignore[import-not-found]
    except Exception:
        return "dev"
    return STAMP or "dev"


# Resolved once at import. In a checkout this is "dev" (source hashing — not this
# stamp — keys the cache there); a frozen build carries the baked value, so two
# same-version builds with different code do not collide on a cache key.
_BUILD_STAMP = _read_build_stamp()


def build_identity() -> str:
    """A string identifying this build: ``"<version>+<stamp>"``.

    Stable within one build, distinct across builds whose code differs. Used as
    the frozen-build substitute for hashing module source in the output cache.
    """
    return f"{__version__}+{_BUILD_STAMP}"

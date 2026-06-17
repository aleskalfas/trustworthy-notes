"""Shared internals used by project-management's verb-subject scripts.

Per DEC-021 + DEC-020, capability scripts share a small set of helpers
(identity resolution, the membership predicate, common formatting).
Each script remains PEP 723 self-contained; this package is loaded by
each script via a `sys.path` insertion of its parent directory.
"""

"""Durable orchestration boundary.

Only modules in this package and the worker entrypoint may depend on DBOS.
Domain, policy, persistence, authority, and effect semantics remain DBOS-neutral.
"""

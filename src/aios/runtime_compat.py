"""Shared external compatibility profile for World Runtime clients.

These constants describe the product-level protocol boundary expected by domain
controllers. Contract subsets remain owner-specific at each bridge.
"""

WORLD_RUNTIME_PROTOCOL = "4.0"
SEMANTIC_KERNEL_VERSION = "0.3.0"

__all__ = ["SEMANTIC_KERNEL_VERSION", "WORLD_RUNTIME_PROTOCOL"]

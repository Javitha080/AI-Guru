"""
Resource Governor Re-export Module.
"""

from deeptutor.services.governor import (
    ResourceGovernor,
    get_resource_governor,
)

__all__ = [
    "ResourceGovernor",
    "get_resource_governor",
]

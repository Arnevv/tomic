"""Shared configuration model utilities.

This module defines small Pydantic helpers that are reused across
configuration models.  At the moment it only exposes :class:`ConfigBase`
which provides a ``version`` field so individual configuration files can
declare their schema version explicitly.
"""

from pydantic import BaseModel, ConfigDict


class ConfigBase(BaseModel):
    """Base model for configuration files.

    All configuration roots should inherit from this model to ensure a
    ``version`` attribute is present.  The field does not currently have any
    semantics besides being an integer but it lays the groundwork for future
    schema migrations.
    """

    version: int

    # Reject unexpected fields to surface typos early.
    model_config = ConfigDict(extra="forbid")


__all__ = ["ConfigBase"]


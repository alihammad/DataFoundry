"""Transformation ABC (feature 003, T008).

Each transformation type implements ``apply`` returning a
:class:`TransformationResult` (clean rows + quarantined rows). The registry
maps ``logic.type`` -> implementation (mirrors capability-registry pattern,
FR-015 spirit).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa


@dataclass
class TransformationResult:
    """Output of a transformation: clean rows + quarantined rows."""

    table: pa.Table
    quarantined: list[dict[str, Any]] = field(default_factory=list)


class Transformation(abc.ABC):
    """Base class for a transformation implementation."""

    logic_type: str = ""

    @abc.abstractmethod
    def apply(
        self,
        *,
        input_table: pa.Table,
        logic: dict[str, Any],
        dedup_keys: list[str] | None = None,
    ) -> TransformationResult:
        """Transform an input table into the target layer's output.

        Returns clean rows plus any malformed records routed to quarantine
        (FR-006). Implementations must not raise on malformed input — they
        quarantine instead.
        """

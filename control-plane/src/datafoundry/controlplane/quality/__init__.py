"""Quality control engine for the DataFoundry control plane.

Implements the shift-left data quality gates (feature 004): quality gates at
every Medallion layer transition, configurable tests with severity, data
contracts, quarantine with replay, controlled overrides, and quality
observability. Consumed by feature 003 (medallion-processing) as the promotion
condition.
"""

from __future__ import annotations

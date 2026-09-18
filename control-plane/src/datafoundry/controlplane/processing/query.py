"""Analyst querying (feature 003, T042).

DuckDB querying over Silver/Gold Iceberg tables (lightweight, no warehouse
load, FR-016). Surfaces schema/quality score/freshness before querying and
applies column-level protection on download (FR-016, US5-AC3).
"""

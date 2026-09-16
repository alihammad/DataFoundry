"""Ingestion engine core.

Executes the batch pipeline ``extract -> validate -> land/quarantine``,
staging-then-commit Bronze landing, batch metadata writes, and per-source
high-watermark persistence.
"""

"""In-process ingestion scheduler.

Background thread ticker querying due pipelines and dispatching runs through
the feature 001 dispatcher hook. Schedules evaluated in platform timezone;
paused pipelines skipped.
"""

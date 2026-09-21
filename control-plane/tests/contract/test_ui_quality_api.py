"""Contract tests for the quality/monitoring data sources (feature 007, T037).

Covers quality score/history, report drill-down, contracts, overrides per
ui-contract.md §6.
"""

from __future__ import annotations

import uuid


class TestQualityDataSources:
    def test_quality_score_missing_dataset_404(self, client):
        resp = client.get(f"/api/v1/datasets/{uuid.uuid4()}/quality")
        assert resp.status_code == 404

    def test_quality_history_missing_dataset_404(self, client):
        resp = client.get(f"/api/v1/datasets/{uuid.uuid4()}/quality/history")
        assert resp.status_code == 404

    def test_report_missing_404(self, client):
        resp = client.get(f"/api/v1/reports/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_contracts_missing_dataset_404(self, client):
        resp = client.get(f"/api/v1/datasets/{uuid.uuid4()}/contracts")
        assert resp.status_code == 404

    def test_overrides_missing_dataset_404(self, client):
        resp = client.get(f"/api/v1/datasets/{uuid.uuid4()}/overrides")
        assert resp.status_code == 404

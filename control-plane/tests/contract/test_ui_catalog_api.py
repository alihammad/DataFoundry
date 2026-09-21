"""Contract tests for the catalog/query data sources (feature 007, T031).

Covers saved-query create/run/share per ui-api.md §2 and ui-contract.md §5.
"""

from __future__ import annotations


class TestCatalogDataSources:
    def test_create_saved_query(self, client):
        resp = client.post(
            "/api/v1/ui/saved-queries",
            json={
                "name": "revenue",
                "sql_text": "SELECT * FROM gold_orders",
                "dataset_bindings": ["gold_orders"],
            },
        )
        assert resp.status_code == 201, resp.text
        assert "query_id" in resp.json()

    def test_run_saved_query(self, client):
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        ).json()["query_id"]
        resp = client.post(f"/api/v1/ui/saved-queries/{qid}/run")
        assert resp.status_code == 200
        assert resp.json()["sql_text"] == "SELECT * FROM gold_orders"

    def test_share_saved_query(self, client):
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        ).json()["query_id"]
        resp = client.post(
            f"/api/v1/ui/saved-queries/{qid}/share",
            json={"shared_with_identity": "analyst@acme.com"},
        )
        assert resp.status_code == 201, resp.text
        assert "share_id" in resp.json()

    def test_get_saved_query_owner(self, client):
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        ).json()["query_id"]
        resp = client.get(f"/api/v1/ui/saved-queries/{qid}")
        assert resp.status_code == 200
        assert resp.json()["sql_text"] == "SELECT * FROM gold_orders"

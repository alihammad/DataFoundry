check "encryption_enforced_in_production" {
  assert {
    condition     = var.environment != "production" || var.encryption_enforced
    error_message = "FR-017: encryption_enforced must be true in production."
  }
}

locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "monitoring"
  })
}

# GCP monitoring capability (T059): Cloud Monitoring dashboard + alerts
# (OTel collector ships via the platform workloads); synthetic-datapoint
# health target.

resource "google_monitoring_dashboard" "platform" {
  dashboard_json = jsonencode({
    displayName = "DataFoundry ${var.platform_name} overview"
    gridLayout = {
      columns = 2
      widgets = [
        {
          title = "Synthetic datapoint"
          xyChart = {
            dataSets = [
              {
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"custom.googleapis.com/datafoundry/synthetic_datapoint\" resource.type=\"global\""
                    aggregation = {
                      alignmentPeriod   = "300s"
                      perSeriesAligner  = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
              },
            ]
          }
        },
      ]
    }
  })
}

resource "google_monitoring_alert_policy" "synthetic" {
  display_name = "${local.name_prefix}-synthetic-datapoint"
  combiner     = "OR"

  conditions {
    display_name = "Synthetic datapoint missing"

    condition_threshold {
      filter          = "metric.type=\"custom.googleapis.com/datafoundry/synthetic_datapoint\" resource.type=\"global\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "600s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.platform"]
      }

      trigger {
        count = 2
      }
    }
  }

  documentation {
    content = "Synthetic datapoint stopped reaching monitoring (R-08)."
  }
}

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

# AWS monitoring capability (T048): OTel collector log pipeline, dashboards,
# alerts; synthetic-datapoint health target.

resource "aws_cloudwatch_log_group" "otel" {
  name              = "/datafoundry/${local.name_prefix}/otel"
  retention_in_days = 30

  tags = local.all_tags
}

resource "aws_cloudwatch_dashboard" "platform" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "DataFoundry platform health"
          region = var.region
          metrics = [
            ["DataFoundry", "SyntheticDatapoint", "Platform", var.platform_name],
          ]
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "synthetic" {
  alarm_name          = "${local.name_prefix}-synthetic-datapoint"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "SyntheticDatapoint"
  namespace           = "DataFoundry"
  period              = 300
  statistic           = "SampleCount"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_description   = "Synthetic datapoint stopped reaching the collector (R-08)."

  dimensions = {
    Platform = var.platform_name
  }

  tags = local.all_tags
}

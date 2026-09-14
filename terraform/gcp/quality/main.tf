locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "quality"
  })
}

# GCP quality capability — PLACEHOLDER (T060).
# Full behaviour delivered by feature 004; implements the common contract
# with a runner-heartbeat health target.

resource "google_service_account" "quality_runner" {
  account_id   = "${local.name_prefix}-quality"
  display_name = "DataFoundry quality runner placeholder (${var.platform_name})"
}

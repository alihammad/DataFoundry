locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "iam"
  })
}

# GCP iam capability (T053): least-privilege service accounts per workload.

data "google_project" "current" {}

locals {
  workloads = ["catalog", "orchestration", "ingestion", "monitoring"]
}

resource "google_service_account" "workload" {
  for_each = toset(local.workloads)

  account_id   = "${local.name_prefix}-${each.value}"
  display_name = "DataFoundry ${each.value} workload (${var.platform_name})"
}

# Least privilege: workloads only get object access to the platform bucket.
resource "google_storage_bucket_iam_member" "workload_data" {
  for_each = toset(local.workloads)

  bucket = "datafoundry-${var.platform_name}-${var.environment}-${var.region}-data"
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.workload[each.value].email}"
}

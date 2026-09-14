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
    capability  = "storage"
  })
}

# GCP storage capability (T052): GCS bucket with zone prefixes, GCS
# native-locking state backend (R-05), CMEK encryption, Bronze immutability
# via object versioning + retention on the bronze zone.

resource "google_storage_bucket" "platform" {
  name     = "${local.name_prefix}-${var.region}-data"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_ref
  }

  lifecycle_rule {
    condition {
      matches_prefix = ["silver/", "gold/"]
      age            = 365
    }
    action {
      type = "Delete"
    }
  }

  labels = local.all_tags
}

# Bronze zone immutability (constitution Principle III): separate bucket with
# a locked retention policy — raw data cannot be deleted or overwritten.
resource "google_storage_bucket" "bronze" {
  name     = "${local.name_prefix}-${var.region}-bronze"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_ref
  }

  retention_policy {
    is_locked        = true
    retention_period = 315360000 # 10 years (immutable/forever posture)
  }

  labels = local.all_tags
}

resource "google_storage_bucket_object" "zone_markers" {
  for_each = toset(["bronze", "silver", "gold"])

  bucket  = google_storage_bucket.platform.name
  name    = "${each.value}/.datafoundry-keep"
  content = ""
}

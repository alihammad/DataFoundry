locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "database"
  })
}

# GCP database capability (T055): Cloud SQL PostgreSQL 15, CMEK-encrypted
# (FR-017), private-only (pg-ping health target).

resource "google_sql_database_instance" "platform" {
  name             = "${local.name_prefix}-db"
  database_version = "POSTGRES_15"
  region           = var.region

  encryption_key_name = var.kms_key_ref

  settings {
    tier              = "db-f1-micro"
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"

    ip_configuration {
      ipv4_enabled    = false
  private_network = var.network_ref
    }

    backup_configuration {
      enabled = true
    }

    deletion_protection_enabled = var.environment == "production"
  }

  deletion_protection = false

  labels = local.all_tags
}

resource "google_sql_database" "datafoundry" {
  name     = "datafoundry"
  instance = google_sql_database_instance.platform.name
}

locals {
  all_labels = merge(var.labels, {
    managed_by = "datafoundry"
    component  = "controlplane"
  })
}

# -- KMS (FR-017: CMEK for the metadata store) --------------------------------

resource "google_kms_key_ring" "metadata" {
  name     = "${var.name_prefix}-keyring"
  location = var.region
}

resource "google_kms_crypto_key" "metadata" {
  name            = "${var.name_prefix}-metadata-cmek"
  key_ring        = google_kms_key_ring.metadata.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = false
  }
}

# -- Metadata store (Cloud SQL PostgreSQL, CMEK, private) ---------------------

resource "google_sql_database_instance" "metadata" {
  name             = "${var.name_prefix}-metadata"
  database_version = "POSTGRES_15"
  region           = var.region

  encryption_key_name = google_kms_crypto_key.metadata.id

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.controlplane.id
    }

    backup_configuration {
      enabled = true
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "datafoundry" {
  name     = "datafoundry"
  instance = google_sql_database_instance.metadata.name
}

resource "google_sql_user" "dfadmin" {
  name     = var.database_username
  instance = google_sql_database_instance.metadata.name
}

# -- Networking ---------------------------------------------------------------

resource "google_compute_network" "controlplane" {
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private" {
  name          = "${var.name_prefix}-private"
  network       = google_compute_network.controlplane.id
  region        = var.region
  ip_cidr_range = "10.0.0.0/20"

  private_ip_google_access = true
}

# -- Compute (Cloud Run) ------------------------------------------------------

resource "google_service_account" "controlplane" {
  account_id   = "${var.name_prefix}-sa"
  display_name = "DataFoundry control plane (${var.name_prefix})"
}

resource "google_cloud_run_service" "controlplane" {
  name     = "${var.name_prefix}"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.controlplane.email

      containers {
        image = var.controlplane_image

        env {
          name  = "DF_DATABASE_URL"
          value = "postgresql+psycopg://${var.database_username}:@/datafoundry?host=/cloudsql/${var.project_id}:${var.region}:${google_sql_database_instance.metadata.name}"
        }
        env {
          name  = "DF_AUTH_MODE"
          value = "cloud_iam"
        }

        ports {
          container_port = 8000
        }
      }
    }

    metadata {
      annotations = {
        "run.googleapis.com/cloudsql-instances" = "${var.project_id}:${var.region}:${google_sql_database_instance.metadata.name}"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  labels = local.all_labels
}

# TLS-only: enforce HTTPS redirect + public access via IAM (managed HTTPS).
resource "google_cloud_run_service_iam_member" "public" {
  service  = google_cloud_run_service.controlplane.name
  location = google_cloud_run_service.controlplane.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

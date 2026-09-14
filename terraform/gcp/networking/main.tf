locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "networking"
  })
}

# GCP networking capability (T050): VPC, private isolation, CIDR — mirrors the
# AWS contract (SC-003 parity).

resource "google_compute_network" "platform" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false

  description = "DataFoundry platform network (${var.platform_name}/${var.environment})"
}

resource "google_compute_subnetwork" "private" {
  name          = "${local.name_prefix}-private"
  network       = google_compute_network.platform.id
  region        = var.region
  ip_cidr_range = "10.0.0.0/16"

  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Private Google access only — no external IPs on platform workloads
# (private isolation, FR-017 posture).
resource "google_compute_firewall" "deny_ingress" {
  name    = "${local.name_prefix}-deny-ingress"
  network = google_compute_network.platform.id

  direction = "INGRESS"
  priority  = 65534

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "allow_tls_egress" {
  name    = "${local.name_prefix}-allow-tls-egress"
  network = google_compute_network.platform.id

  direction = "EGRESS"
  priority  = 1000

  destination_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

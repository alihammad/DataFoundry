locals {
  name_prefix = "datafoundry-${var.platform_name}-${var.environment}"
  all_tags = merge(var.tags, {
    platform    = var.platform_name
    environment = var.environment
    managed_by  = "datafoundry"
    capability  = "compute"
  })
}

# GCP compute capability (T054): GKE cluster sized per config.

variable "size" {
  description = "Compute size: small | medium | large."
  type        = string
  default     = "small"

  validation {
    condition     = contains(["small", "medium", "large"], var.size)
    error_message = "size must be one of: small, medium, large."
  }
}

locals {
  node_count = { small = 1, medium = 2, large = 3 }[var.size]
  machine    = { small = "e2-standard-2", medium = "e2-standard-4", large = "e2-standard-8" }[var.size]
}

resource "google_container_cluster" "platform" {
  name     = "${local.name_prefix}-gke"
  location = var.region

  network    = var.network_ref
  subnetwork = "datafoundry-${var.platform_name}-${var.environment}-private"

  initial_node_count       = 1
  remove_default_node_pool = true

  node_pool {
    name               = "workloads"
    initial_node_count = local.node_count
    machine_type       = local.machine

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  resource_labels = local.all_tags
}

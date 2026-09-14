# Common outputs (capability-catalog.md) + network_ref extra for wiring.

output "endpoint" {
  description = "Logical endpoint (none for networking)."
  value       = ""
}

output "resource_ids" {
  description = "Provider-native ids for audit."
  value       = [google_compute_network.platform.id, google_compute_subnetwork.private.id]
}

output "health_target" {
  description = "dns-resolve probe target."
  value       = google_compute_network.platform.name
}

output "iam_principal" {
  description = "No service identity for networking."
  value       = ""
}

output "network_ref" {
  description = "Network self-link consumed by dependent capability modules."
  value       = google_compute_network.platform.self_link
}

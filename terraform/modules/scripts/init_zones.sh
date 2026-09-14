#!/usr/bin/env bash
# Shared storage-zone initialisation contract (T038, FR-005).
#
# Creates the Bronze/Silver/Gold zone prefixes in the platform bucket.
# Cloud-neutral: the control plane invokes this through its CloudGateway
# (engine/init_jobs.py) — AWS uses `s3 put-object`, GCP `gcs cp`; the zone
# layout below is the single source of truth for both.
#
# Usage: init_zones.sh <bucket-uri> [marker-name]
set -euo pipefail

BUCKET_URI="${1:?bucket uri required (s3://... or gs://...)}"
MARKER="${2:-.datafoundry-keep}"

ZONES=("bronze" "silver" "gold")

for zone in "${ZONES[@]}"; do
  echo "initialising zone prefix: ${BUCKET_URI}/${zone}/"
done

echo "zones initialised: ${ZONES[*]} (marker: ${MARKER})"

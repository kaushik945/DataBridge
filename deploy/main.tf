terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    google = { source = "hashicorp/google", version = "6.49.0" }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "bucket_name" { type = string }
resource "google_project_service" "apis" {
  for_each           = toset(["run.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com", "secretmanager.googleapis.com", "aiplatform.googleapis.com", "artifactregistry.googleapis.com"])
  service            = each.key
  disable_on_destroy = false
}
resource "google_service_account" "app" {
  account_id   = "databridge-app"
  display_name = "DataBridge runtime"
}
resource "google_project_iam_member" "runtime" {
  project  = var.project_id
  for_each = toset(["roles/cloudsql.client", "roles/aiplatform.user"])
  role     = each.key
  member   = "serviceAccount:${google_service_account.app.email}"
}
resource "google_sql_database_instance" "db" {
  name                = "databridge-db"
  database_version    = "POSTGRES_16"
  deletion_protection = true
  settings {
    tier    = "db-f1-micro"
    edition = "ENTERPRISE"
    backup_configuration { enabled = true }
    ip_configuration {
      ipv4_enabled = true
      # No authorized networks: connect through Cloud SQL's authenticated connector.
    }
  }
  depends_on = [google_project_service.apis]
}
resource "google_sql_database" "app" {
  name     = "databridge"
  instance = google_sql_database_instance.db.name
}
resource "google_storage_bucket" "uploads" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  lifecycle_rule {
    condition { age = 30 }
    action { type = "Delete" }
  }
}
resource "google_storage_bucket_iam_member" "writer" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.app.email}"
}
resource "google_secret_manager_secret" "database" {
  secret_id = "databridge-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_iam_member" "database" {
  secret_id = google_secret_manager_secret.database.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}
output "sql_connection_name" { value = google_sql_database_instance.db.connection_name }
output "runtime_service_account" { value = google_service_account.app.email }

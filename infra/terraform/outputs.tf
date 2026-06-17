output "ml_data_bucket_name" {
  value = module.ml_data.bucket_name
}

output "ml_data_bucket_arn" {
  value = module.ml_data.bucket_arn
}

output "ml_data_kms_key_arn" {
  value = module.ml_data.kms_key_arn
}

output "github_actions_role_arn" {
  value = module.ml_data.github_actions_role_arn
}

output "bucket_name" {
  value = aws_s3_bucket.ml_data.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.ml_data.arn
}

output "kms_key_arn" {
  value = aws_kms_key.ml_data_key.arn
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions_role.arn
}

output "athena_workgroup_name" {
  value = aws_athena_workgroup.logs.name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.logs.name
}

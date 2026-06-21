# state を module.ml_data に移行する moved ブロック。
# terraform apply で state 移行が完了したら、このファイルは削除してよい。

moved {
  from = aws_kms_key.ml_data_key
  to   = module.ml_data.aws_kms_key.ml_data_key
}

moved {
  from = aws_s3_bucket.ml_data
  to   = module.ml_data.aws_s3_bucket.ml_data
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.ml_data
  to   = module.ml_data.aws_s3_bucket_server_side_encryption_configuration.ml_data
}

moved {
  from = aws_s3_bucket_public_access_block.ml_data
  to   = module.ml_data.aws_s3_bucket_public_access_block.ml_data
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.ml_data
  to   = module.ml_data.aws_s3_bucket_lifecycle_configuration.ml_data
}

moved {
  from = aws_s3_bucket.ml_data_log
  to   = module.ml_data.aws_s3_bucket.ml_data_log
}

moved {
  from = aws_s3_bucket_public_access_block.ml_data_log
  to   = module.ml_data.aws_s3_bucket_public_access_block.ml_data_log
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.ml_data_log
  to   = module.ml_data.aws_s3_bucket_lifecycle_configuration.ml_data_log
}

moved {
  from = aws_s3_bucket_logging.ml_data
  to   = module.ml_data.aws_s3_bucket_logging.ml_data
}

moved {
  from = aws_iam_role.github_actions_role
  to   = module.ml_data.aws_iam_role.github_actions_role
}

moved {
  from = aws_iam_role_policy.github_actions_role_policy
  to   = module.ml_data.aws_iam_role_policy.github_actions_role_policy
}

moved {
  from = module.iam_eks[0].aws_iam_role.argo_workflows
  to   = module.iam_eks[0].aws_iam_role.ml_workflow
}

moved {
  from = module.iam_eks[0].aws_iam_role_policy.argo_workflows
  to   = module.iam_eks[0].aws_iam_role_policy.ml_workflow
}

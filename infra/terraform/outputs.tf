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

# Network
output "vpc_id" {
  value = try(module.network[0].vpc_id, null)
}

# EKS
output "eks_cluster_name" {
  value = try(module.eks[0].cluster_name, null)
}

output "eks_cluster_endpoint" {
  value = try(module.eks[0].cluster_endpoint, null)
}

output "eks_developer_role_arn" {
  value = try(module.eks[0].developer_role_arn, null)
}

output "kubeconfig_command" {
  value = try("aws eks update-kubeconfig --name ${module.eks[0].cluster_name} --region ap-northeast-1 --role-arn ${module.eks[0].developer_role_arn}", null)
}

# ECR
output "ecr_urls" {
  value = try(module.ecr[0].repository_urls, null)
}

# RDS
output "rds_endpoint" {
  value = try(module.rds[0].endpoint, null)
}

output "rds_db_name" {
  value = try(module.rds[0].db_name, null)
}

# IRSA
output "argo_workflows_role_arn" {
  value = try(module.iam_eks[0].argo_workflows_role_arn, null)
}

output "mlflow_role_arn" {
  value = try(module.iam_eks[0].mlflow_role_arn, null)
}

output "lbc_role_arn" {
  value = try(module.iam_eks[0].lbc_role_arn, null)
}

output "weather_api_role_arn" {
  value = try(module.iam_eks[0].weather_api_role_arn, null)
}

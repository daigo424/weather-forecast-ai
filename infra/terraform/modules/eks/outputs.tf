output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "cluster_certificate_authority_data" {
  value = aws_eks_cluster.main.certificate_authority[0].data
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "oidc_provider_url" {
  value = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

output "developer_role_arn" {
  value = aws_iam_role.eks_developer.arn
}

output "karpenter_role_arn" {
  value = aws_iam_role.karpenter.arn
}

output "karpenter_queue_name" {
  value = aws_sqs_queue.karpenter.name
}

output "node_role_name" {
  value = aws_iam_role.node.name
}

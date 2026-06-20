variable "aws_region" {
  type = string
}

variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "compute_enabled" {
  type        = bool
  default     = false
  description = "EKS・NAT・IRSA を作成するか（false で削除。RDS・S3 は保持）"
}

variable "eks_version" {
  type    = string
  default = "1.32"
}

variable "vpc_cidr" {
  type        = string
  description = "既存 VPC の CIDR（network モジュールで VPC 検索に使用）"
}

variable "developer_iam_role_paths" {
  type        = list(string)
  default     = []
  description = "ローカル開発者の IAM ロールパス（account ID を除いた部分）例: role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_..."
}

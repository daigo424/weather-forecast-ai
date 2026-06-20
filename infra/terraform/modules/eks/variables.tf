variable "name_prefix" {
  type = string
}

variable "eks_version" {
  type    = string
  default = "1.32"
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "developer_iam_role_paths" {
  type        = list(string)
  default     = []
  description = "ローカル開発者の IAM ロールパス（account ID を除いた部分）例: role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_..."
}

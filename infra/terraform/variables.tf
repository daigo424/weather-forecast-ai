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
  description = "EKS・NAT・VPC Endpoint・Bastion・IRSA を作成するか（false で削除。RDS・S3・VPC・Subnet は保持）"
}

variable "retain_on_idle" {
  type        = bool
  default     = true
  description = "compute_enabled=false の間も ECR・Secrets Manager 等の状態を保持するか（false かつ compute_enabled=false で完全削除。長期放置してコストをゼロにしたい場合に false にする）"
}

variable "eks_version" {
  type    = string
  default = "1.32"
}

variable "vpc_cidr" {
  type        = string
  description = "既存 VPC の CIDR（network モジュールで VPC 検索に使用）"
}

variable "docker_hub_username" {
  type      = string
  sensitive = true
}

variable "docker_hub_access_token" {
  type      = string
  sensitive = true
}

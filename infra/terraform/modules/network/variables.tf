variable "name_prefix" {
  type = string
}

variable "vpc_cidr" {
  type        = string
  description = "既存 VPC の CIDR（VPC 検索に使用）"
}

variable "azs" {
  type = list(string)
}

variable "create_nat" {
  type = bool
}

variable "create_endpoints" {
  type = bool
}

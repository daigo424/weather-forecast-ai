variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "db_username" {
  type    = string
  default = "admin"
}

variable "allowed_cidrs" {
  type        = list(string)
  default     = []
  description = "Additional CIDRs to allow access to RDS (e.g. VPN IPs for local development)"
}

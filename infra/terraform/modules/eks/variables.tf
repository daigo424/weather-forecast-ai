variable "name_prefix" {
  type = string
}

variable "eks_version" {
  type    = string
  default = "1.34"
}

variable "private_subnet_ids" {
  type = list(string)
}


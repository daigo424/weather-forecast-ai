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


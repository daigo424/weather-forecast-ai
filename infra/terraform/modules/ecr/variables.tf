variable "name_prefix" {
  type = string
}

variable "services" {
  type    = list(string)
  default = []
}

variable "docker_hub_username" {
  type      = string
  sensitive = true
}

variable "docker_hub_access_token" {
  type      = string
  sensitive = true
}

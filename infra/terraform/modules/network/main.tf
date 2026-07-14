data "aws_vpc" "main" {
  cidr_block = var.vpc_cidr
}

resource "aws_internet_gateway" "main" {
  vpc_id = data.aws_vpc.main.id

  tags = {
    Name = "${var.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  count = length(var.azs)

  vpc_id                  = data.aws_vpc.main.id
  cidr_block              = cidrsubnet(data.aws_vpc.main.cidr_block, 4, count.index)
  availability_zone       = var.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                       = "${var.name_prefix}-public-${count.index}"
    "kubernetes.io/role/elb"                   = "1"
    "kubernetes.io/cluster/${var.name_prefix}" = "shared"
  }
}

resource "aws_subnet" "private" {
  count = length(var.azs)

  vpc_id            = data.aws_vpc.main.id
  cidr_block        = cidrsubnet(data.aws_vpc.main.cidr_block, 4, count.index + 10)
  availability_zone = var.azs[count.index]

  tags = {
    Name                                       = "${var.name_prefix}-private-${count.index}"
    "kubernetes.io/role/internal-elb"          = "1"
    "kubernetes.io/cluster/${var.name_prefix}" = "owned"
    "karpenter.sh/discovery"                   = var.name_prefix
  }
}

resource "aws_eip" "nat" {
  count  = var.create_nat ? 1 : 0
  domain = "vpc"

  tags = {
    Name = "${var.name_prefix}-nat-eip"
  }
}

# AWS doesn't immediately release the EIP's internal ENI association after NAT Gateway
# deletion, causing a race condition. Sleeping 3m on destroy gives AWS time to finish
# the cleanup before the EIP release is attempted.
resource "time_sleep" "wait_after_nat_destroy" {
  count = var.create_nat ? 1 : 0

  depends_on       = [aws_eip.nat]
  destroy_duration = "3m"
}

resource "aws_nat_gateway" "main" {
  count = var.create_nat ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  depends_on = [time_sleep.wait_after_nat_destroy]

  tags = {
    Name = "${var.name_prefix}-nat"
  }
}

resource "aws_route_table" "public" {
  vpc_id = data.aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = length(var.azs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = data.aws_vpc.main.id

  dynamic "route" {
    for_each = var.create_nat ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[0].id
    }
  }

  tags = {
    Name = "${var.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count = length(var.azs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

data "aws_region" "current" {}

resource "aws_security_group" "ecr_endpoint" {
  count  = var.create_endpoints ? 1 : 0
  name   = "${var.name_prefix}-ecr-endpoint-sg"
  vpc_id = data.aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.main.cidr_block]
  }

  tags = {
    Name = "${var.name_prefix}-ecr-endpoint-sg"
  }
}

resource "aws_vpc_endpoint" "s3" {
  count             = var.create_endpoints ? 1 : 0
  vpc_id            = data.aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "${var.name_prefix}-s3-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_api" {
  count               = var.create_endpoints ? 1 : 0
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.ecr_endpoint[0].id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-ecr-api-endpoint"
  }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count               = var.create_endpoints ? 1 : 0
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.ecr_endpoint[0].id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-ecr-dkr-endpoint"
  }
}

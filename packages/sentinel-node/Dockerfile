# Sentinel Node - Go Validator Node
# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git make protoc protobuf-dev

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Generate protobuf code
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && \
    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest && \
    protoc --go_out=. --go-grpc_out=. pkg/proto/sentinel.proto || true

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o sentinel ./cmd/sentinel

# Runtime stage
FROM alpine:3.19

WORKDIR /app

# Install ca-certificates for HTTPS
RUN apk add --no-cache ca-certificates

# Copy binary from builder
COPY --from=builder /app/sentinel .
COPY --from=builder /app/configs ./configs

# Create non-root user
RUN adduser -D -g '' sentinel
USER sentinel

# Expose ports
EXPOSE 8080
EXPOSE 9090
EXPOSE 4001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Run node
ENTRYPOINT ["./sentinel"]
CMD ["--config", "./configs/config.yaml"]

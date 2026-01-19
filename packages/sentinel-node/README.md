# Sentinel Node

High-performance Go node software for the Sentinel Protocol. Monitors the Ethereum mempool, runs AI inference, and participates in consensus to protect DeFi protocols.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Sentinel Node                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Mempool    │───▶│   Inference  │───▶│   Consensus  │          │
│  │   Listener   │    │    Bridge    │    │   (Gossip)   │          │
│  │              │    │              │    │              │          │
│  │  WebSocket   │    │  gRPC→Python │    │   libp2p     │          │
│  │  go-ethereum │    │  + fallback  │    │   BLS sigs   │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│   Pending Txs        Risk Score          Pause Request             │
│   10k+ tx/s          <300ms latency      20/30 threshold           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### Mempool Listener

High-speed WebSocket connection to Ethereum nodes for real-time pending transaction monitoring.

**Features:**
- WebSocket subscription to `pendingTransactions`
- Configurable buffer (default: 10,000 txs)
- Transaction simulation via `eth_call`
- Statistics tracking (received, processed, dropped)

### Inference Bridge

gRPC client connecting to the Python sentinel-brain inference engine.

**Features:**
- Timeout-based fallback to local heuristics
- Configurable anomaly threshold
- Batch analysis support
- Quick filter for obvious safe transactions

### Consensus (Gossip)

P2P network for node coordination using libp2p.

**Features:**
- GossipSub protocol for message propagation
- BLS signature aggregation (BN254 curve)
- Heartbeat-based peer discovery
- Pause request coordination

### BLS Signatures

BLS12-381 compatible signatures using gnark-crypto.

**Features:**
- Key pair generation and persistence
- Single and aggregated signature creation
- Signature verification
- Public key aggregation

## Installation

### Prerequisites

- Go 1.22+
- Access to Ethereum RPC (Alchemy, Infura, etc.)
- (Optional) Running sentinel-brain inference server

### Building

```bash
cd packages/sentinel-node

# Download dependencies
go mod download

# Build binary
go build -o sentinel ./cmd/sentinel

# Or install to GOPATH
go install ./cmd/sentinel
```

## Configuration

### Configuration File (config.yaml)

```yaml
node:
  name: "sentinel-node-1"
  dataDir: "./data"
  privateKeyPath: "./keys/node.key"
  blsKeyPath: "./keys/bls.key"
  metricsPort: 9090
  apiPort: 8080
  shutdownTimeout: 30s

ethereum:
  rpcUrl: "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
  wsUrl: "wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
  chainId: 1
  blockConfirmations: 1
  txTimeout: 5m
  maxGasPrice: 500000000000

p2p:
  listenAddresses:
    - "/ip4/0.0.0.0/tcp/9000"
  bootstrapPeers:
    - "/ip4/1.2.3.4/tcp/9000/p2p/QmPeerId..."
  maxPeers: 50
  topicName: "sentinel/v1/alerts"
  heartbeatInterval: 10s

inference:
  grpcAddress: "localhost:50051"
  timeout: 300ms
  batchSize: 10
  enableSimulation: true
  anomalyThreshold: 0.65

contracts:
  tokenAddress: "0x..."
  registryAddress: "0x..."
  shieldAddress: "0x..."
  routerAddress: "0x..."

logging:
  level: "info"
  format: "json"
  outputPath: "stdout"
```

### Environment Variables

All configuration can be overridden via environment variables:

```bash
export SENTINEL_NODE_NAME="my-node"
export SENTINEL_ETH_RPC_URL="https://..."
export SENTINEL_ETH_WS_URL="wss://..."
export SENTINEL_INFERENCE_GRPC="localhost:50051"
export SENTINEL_LOG_LEVEL="debug"
```

## Running

### Basic Usage

```bash
# With config file
./sentinel --config config.yaml

# With debug logging
./sentinel --config config.yaml --log-level debug
```

### Docker

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY . .
RUN go build -o sentinel ./cmd/sentinel

FROM alpine:latest
COPY --from=builder /app/sentinel /usr/local/bin/
COPY config.yaml /etc/sentinel/
ENTRYPOINT ["sentinel", "--config", "/etc/sentinel/config.yaml"]
```

```bash
docker build -t sentinel-node .
docker run -v ./keys:/keys sentinel-node
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sentinel-node
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sentinel-node
  template:
    spec:
      containers:
        - name: sentinel
          image: sentinel-node:latest
          ports:
            - containerPort: 9000  # P2P
            - containerPort: 9090  # Metrics
            - containerPort: 8080  # API
          volumeMounts:
            - name: keys
              mountPath: /keys
            - name: config
              mountPath: /etc/sentinel
      volumes:
        - name: keys
          secret:
            secretName: sentinel-keys
        - name: config
          configMap:
            name: sentinel-config
```

## Monitoring

### Prometheus Metrics

The node exposes metrics on the configured `metricsPort`:

| Metric | Description |
|--------|-------------|
| `sentinel_txs_analyzed_total` | Total transactions analyzed |
| `sentinel_txs_suspicious_total` | Suspicious transactions detected |
| `sentinel_inference_latency_ms` | Inference latency histogram |
| `sentinel_peers_connected` | Connected P2P peers |
| `sentinel_pause_requests_total` | Pause requests created/signed |

### Logging

Structured JSON logs with zerolog:

```json
{
  "level": "warn",
  "tx": "0x123...",
  "score": 0.82,
  "risk": "high",
  "indicators": ["flash_loan_detected", "high_gas_limit"],
  "message": "Suspicious transaction detected"
}
```

## Development

### Running Tests

```bash
go test ./...
go test -v -race ./...
```

### Local Development

```bash
# Start local Anvil fork
anvil --fork-url $ETH_RPC_URL &

# Start inference server
cd ../sentinel-brain
python -m sentinel_brain.inference.engine --serve &

# Run node
go run ./cmd/sentinel --config config.dev.yaml
```

## Security

### Key Management

- Node private key: Used for Ethereum transactions
- BLS key: Used for consensus signatures

Keys should be stored securely and never committed to version control.

### Network Security

- All P2P communication is authenticated
- BLS signatures prevent message forgery
- Consensus threshold prevents single-node attacks

## License

MIT License

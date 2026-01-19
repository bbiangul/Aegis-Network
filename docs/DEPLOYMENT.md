# Aegis Network - Deployment Guide

This guide covers deploying Aegis Network to testnet (Sepolia) and eventually mainnet.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (Local)](#quick-start-local)
3. [Testnet Deployment (Sepolia)](#testnet-deployment-sepolia)
4. [Running the Full Stack](#running-the-full-stack)
5. [Mainnet Deployment](#mainnet-deployment)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

```bash
# Foundry (Solidity toolchain)
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Go 1.22+
brew install go  # macOS
# or: https://go.dev/dl/

# Python 3.11+
brew install python@3.11  # macOS

# Docker & Docker Compose
brew install docker docker-compose  # macOS

# Node.js (for some tooling)
brew install node  # macOS
```

### Required Accounts & Keys

1. **Alchemy/Infura Account** - For RPC endpoints
   - Sign up at https://www.alchemy.com/ or https://infura.io/
   - Create an app for Sepolia testnet
   - Copy the HTTP and WebSocket URLs

2. **Etherscan API Key** - For contract verification
   - Sign up at https://etherscan.io/
   - Get API key from https://etherscan.io/myapikey

3. **Testnet ETH** - For deployment gas
   - Sepolia faucet: https://sepoliafaucet.com/
   - Alchemy faucet: https://www.alchemy.com/faucets/ethereum-sepolia
   - You need ~0.5 ETH for full deployment

---

## Quick Start (Local)

Deploy and test locally using Anvil (Foundry's local node):

```bash
# 1. Clone and setup
cd ai_crypto_guard
cp .env.example .env

# 2. Install dependencies
cd packages/sentinel-core && forge install && cd ../..
cd packages/sentinel-brain && pip install -e . && cd ../..
cd packages/sentinel-node && go mod download && cd ../..

# 3. Deploy to local Anvil
chmod +x scripts/deploy-contracts.sh
./scripts/deploy-contracts.sh anvil
```

This will:
- Start a local Anvil node (forked from mainnet)
- Deploy all contracts
- Register test nodes and protocols
- Run a full simulation of attack detection

---

## Testnet Deployment (Sepolia)

### Step 1: Configure Environment

```bash
# Copy example env
cp .env.example .env
```

Edit `.env` with your values:

```bash
# RPC Endpoints (from Alchemy/Infura)
SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
SEPOLIA_WS_URL=wss://eth-sepolia.g.alchemy.com/v2/YOUR_KEY

# Generate a new deployer wallet (NEVER use this on mainnet!)
# Run: cast wallet new
DEPLOYER_PRIVATE_KEY=0x...

# Etherscan API key for verification
ETHERSCAN_API_KEY=YOUR_KEY
```

### Step 2: Get Testnet ETH

```bash
# Check your deployer address
cast wallet address $DEPLOYER_PRIVATE_KEY

# Get Sepolia ETH from faucet:
# https://sepoliafaucet.com/
# https://www.alchemy.com/faucets/ethereum-sepolia
```

### Step 3: Deploy Contracts

```bash
# Deploy all contracts to Sepolia
./scripts/deploy-contracts.sh sepolia
```

Expected output:
```
=== SENTINEL PROTOCOL DEPLOYMENT ===

Deployer: 0x...
Chain ID: 11155111

1. Deploying SentinelToken...
   Address: 0x...
2. Deploying SentinelRegistry...
   Address: 0x...
3. Deploying BLSVerifier...
   Address: 0x...
4. Deploying SentinelShield...
   Address: 0x...
5. Deploying SentinelRouter...
   Address: 0x...

=== DEPLOYMENT COMPLETE ===

Add these to your .env file:
SENTINEL_TOKEN_ADDRESS=0x...
SENTINEL_REGISTRY_ADDRESS=0x...
...
```

### Step 4: Update Environment with Contract Addresses

Add the deployed addresses to your `.env`:

```bash
SENTINEL_TOKEN_ADDRESS=0x...
SENTINEL_REGISTRY_ADDRESS=0x...
SENTINEL_SHIELD_ADDRESS=0x...
SENTINEL_ROUTER_ADDRESS=0x...
BLS_VERIFIER_ADDRESS=0x...
```

### Step 5: Setup Testnet Environment

```bash
# Register a node and protocol for testing
./scripts/deploy-contracts.sh sepolia-setup
```

### Step 6: Verify Contracts on Etherscan

Contracts should auto-verify if you used `--verify`. If not:

```bash
cd packages/sentinel-core

# Verify each contract
forge verify-contract $SENTINEL_TOKEN_ADDRESS SentinelToken \
    --chain sepolia \
    --constructor-args $(cast abi-encode "constructor(address)" $DEPLOYER_ADDRESS)

# Repeat for other contracts...
```

---

## Running the Full Stack

### Option A: Docker Compose (Recommended)

```bash
# Build and start all services
docker-compose up --build

# With monitoring (Prometheus + Grafana)
docker-compose --profile monitoring up --build

# Check logs
docker-compose logs -f sentinel-brain
docker-compose logs -f sentinel-node
```

### Option B: Manual Start

**Terminal 1 - Sentinel Brain (ML Service):**
```bash
cd packages/sentinel-brain
source .venv/bin/activate
python -m sentinel_brain.inference.server
```

**Terminal 2 - Sentinel Node (Go):**
```bash
cd packages/sentinel-node
go run cmd/sentinel/main.go
```

### Verify Services Are Running

```bash
# Check brain gRPC
grpcurl -plaintext localhost:50051 list

# Check node health
curl http://localhost:8080/health

# Check node metrics
curl http://localhost:9090/metrics
```

---

## Mainnet Deployment

> ⚠️ **WARNING**: Mainnet deployment requires:
> - Completed security audit
> - Multi-sig wallet for admin functions
> - Thorough testing on testnet
> - Team review of all parameters

### Pre-deployment Checklist

- [ ] All tests passing (`forge test`, `go test ./...`)
- [ ] Security audit completed
- [ ] Multi-sig wallet configured
- [ ] Parameters reviewed (stake amounts, thresholds)
- [ ] Oracle address configured
- [ ] Emergency contacts ready

### Deployment Steps

```bash
# 1. Update .env with mainnet values
ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
DEPLOYER_PRIVATE_KEY=0x...  # Use hardware wallet!

# 2. Deploy (requires typing confirmation)
./scripts/deploy-contracts.sh mainnet
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         ETHEREUM NETWORK                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ SentinelToken│  │SentinelRouter│ │SentinelShield│             │
│  │   (ERC20)   │  │(Pause Logic) │ │  (Bounties)  │             │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                       │
│                 ┌────────┴────────┐                              │
│                 │ SentinelRegistry │                             │
│                 │ (Staking/Nodes)  │                             │
│                 └─────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
                           │
                    WebSocket RPC
                           │
┌─────────────────────────────────────────────────────────────────┐
│                      SENTINEL NODE (Go)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │Mempool Listener│ │P2P Consensus │ │ Contract     │           │
│  │  (WebSocket)  │  │  (libp2p)   │  │ Interaction  │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│         │                                    │                   │
│         └────────────────┬───────────────────┘                   │
│                          │ gRPC                                  │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                   SENTINEL BRAIN (Python)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │Feature Extract│  │Isolation     │  │Protocol      │           │
│  │   Pipeline   │  │  Forest ML   │  │  Filter      │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SEPOLIA_RPC_URL` | Yes | Sepolia HTTP RPC endpoint |
| `SEPOLIA_WS_URL` | Yes | Sepolia WebSocket endpoint |
| `DEPLOYER_PRIVATE_KEY` | Yes | Private key for deployment |
| `NODE_PRIVATE_KEY` | Yes | Node operator private key |
| `ETHERSCAN_API_KEY` | No | For contract verification |
| `ANOMALY_THRESHOLD` | No | ML threshold (default: 0.65) |
| `LOG_LEVEL` | No | debug/info/warn/error |

### Contract Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Min Node Stake | 10,000 SENTR | Minimum to register as node |
| Protocol Stake | Varies | Based on TVL tier |
| Dispute Window | 48 hours | Time to dispute claims |
| Slashing Rate | 50% | Penalty for false positives |
| Signature Threshold | 67% | Required for pause |

---

## Troubleshooting

### "Insufficient funds for gas"

```bash
# Check balance
cast balance $DEPLOYER_ADDRESS --rpc-url $SEPOLIA_RPC_URL

# Get more Sepolia ETH from faucet
```

### "Contract verification failed"

```bash
# Manual verification
forge verify-contract $ADDRESS ContractName \
    --chain sepolia \
    --watch
```

### "gRPC connection refused"

```bash
# Check if brain is running
docker-compose logs sentinel-brain

# Restart services
docker-compose restart sentinel-brain
```

### "P2P connection issues"

```bash
# Check firewall allows port 9000
# Verify bootstrap peers are correct
# Check node logs for peer discovery
docker-compose logs sentinel-node | grep -i peer
```

---

## Monitoring

### Grafana Dashboard

Access at http://localhost:3000 (default: admin/admin)

Pre-configured dashboards:
- Node Health
- Detection Metrics
- P2P Network Status
- Contract Interactions

### Prometheus Metrics

Access at http://localhost:9091

Key metrics:
- `sentinel_transactions_analyzed_total`
- `sentinel_anomalies_detected_total`
- `sentinel_inference_latency_ms`
- `sentinel_peers_connected`

---

## Next Steps

1. **Join Testnet Network**: Connect to other testnet nodes
2. **Monitor Performance**: Watch detection metrics
3. **Report Issues**: https://github.com/sentinel-protocol/issues
4. **Prepare for Mainnet**: Complete audit checklist

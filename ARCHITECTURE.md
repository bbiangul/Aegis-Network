# Aegis Network - Architecture Overview

## What It Does

Aegis is a **DeFi security infrastructure** that detects and prevents hacks by monitoring the Ethereum mempool. When a malicious transaction is detected, the system triggers a defensive pause on the target protocol **before** the attack transaction is confirmed.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ATTACK TIMELINE                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  Attacker submits TX  →  Mempool  →  Block inclusion  →  Funds drained  │
│         ↓                   ↓                                            │
│    [Aegis detects]     [Pause triggered]                                │
│                              ↓                                           │
│                      Protocol paused BEFORE attack executes             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Three Main Components

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          AEGIS NETWORK                                    │
├────────────────────┬─────────────────────┬───────────────────────────────┤
│   sentinel-brain   │   sentinel-node     │   sentinel-core               │
│   (Python/ML)      │   (Go)              │   (Solidity)                  │
├────────────────────┼─────────────────────┼───────────────────────────────┤
│ • AI inference     │ • Mempool listener  │ • SentinelToken ($SENTR)      │
│ • Feature extract  │ • P2P gossip        │ • SentinelRegistry (staking)  │
│ • Anomaly detect   │ • BLS signatures    │ • SentinelRouter (pause exec) │
│ • gRPC server      │ • gRPC client       │ • SentinelShield (bounties)   │
└────────────────────┴─────────────────────┴───────────────────────────────┘
```

---

## 1. sentinel-brain (Python ML)

**Purpose:** Analyze transactions and detect attacks using machine learning.

```
src/sentinel_brain/
├── data/
│   ├── collectors/
│   │   ├── fork_replayer.py      # Replay historical exploits on Anvil fork
│   │   └── mempool_listener.py   # Listen to live mempool
│   └── exploits/
│       └── registry.py           # 70+ known exploits (2022-2025)
│
├── features/
│   ├── extractors/
│   │   ├── flash_loan.py         # Detect flash loan patterns
│   │   ├── state_variance.py     # Storage slot changes (>20% = suspicious)
│   │   ├── bytecode.py           # Contract age, similarity to exploits
│   │   └── opcode.py             # DELEGATECALL, SELFDESTRUCT frequency
│   └── aggregator.py             # Combine all features into vector
│
├── models/
│   ├── isolation_forest.py       # Anomaly detection (scores 0.0-1.0)
│   └── heuristics.py             # Fast pre-filter (95% safe TX filtered)
│
├── inference/
│   └── engine.py                 # Full pipeline: filter → simulate → ML
│
└── grpc/
    └── server.py                 # gRPC server for node communication
```

**Flow:**
```
Transaction → Heuristic Filter → Simulation → Feature Extract → ML Model → Risk Score
     ↓              ↓                ↓              ↓               ↓
  Raw TX      95% filtered      Anvil trace    6 features    0.0-1.0 score
              as "safe"
```

---

## 2. sentinel-node (Go)

**Purpose:** Run the validator node - listen to mempool, coordinate with other nodes, submit pause requests.

```
internal/
├── mempool/
│   └── listener.go       # WebSocket connection to Ethereum RPC
│                         # Receives pending transactions
│
├── inference/
│   └── bridge.go         # gRPC client to sentinel-brain
│                         # Fallback to heuristics if ML unavailable
│
├── consensus/
│   ├── bls.go            # BLS signature generation (gnark-crypto)
│   └── gossip.go         # P2P protocol (libp2p)
│                         # Broadcast alerts, collect signatures
│
└── config/
    └── config.go         # Node configuration
```

**Flow:**
```
Mempool TX → Analyze (gRPC to brain) → Suspicious? → Broadcast Alert
                                            ↓
                    Other nodes sign → Threshold reached (20/30)
                                            ↓
                              Submit to SentinelRouter on-chain
```

---

## 3. sentinel-core (Solidity)

**Purpose:** On-chain contracts for staking, pause execution, and bounty payouts.

```
src/
├── SentinelToken.sol      # $SENTR ERC20 token
│   • 100M initial supply, 1B max
│   • Minting for rewards
│   • Burning for slashing
│
├── SentinelRegistry.sol   # Staking & node management
│   • Node registration (10k $SENTR minimum)
│   • Protocol registration (TVL-tiered: 5k-100k $SENTR)
│   • Slashing for false positives
│   • 21-day unstake cooldown
│
├── SentinelRouter.sol     # Pause execution
│   • Receives signed pause requests
│   • Requires 20/30 (66.67%) node signatures
│   • Calls target protocol's pause() function
│   • 1-hour cooldown between pauses per protocol
│
├── SentinelShield.sol     # Bounty vault
│   • Protocols deposit bounties
│   • 48-hour dispute window after pause
│   • Optimistic verification (pay if no dispute)
│   • Oracle resolution for disputes
│
└── BLSVerifier.sol        # Cryptographic verification
    • Verify aggregated BLS signatures
    • On-chain signature validation
```

---

## Complete Flow: Attack Detection to Pause

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. DETECTION                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Attacker TX → Mempool → sentinel-node (listener.go)                       │
│                               ↓                                              │
│                    gRPC call to sentinel-brain                              │
│                               ↓                                              │
│            Heuristics → Simulation → Feature Extract → Isolation Forest     │
│                               ↓                                              │
│                    Risk Score: 0.87 (HIGH)                                  │
│                               ↓                                              │
│                    "SUSPICIOUS - Flash loan + price manipulation"           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. CONSENSUS                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Node 1 broadcasts alert via libp2p gossip                                 │
│                               ↓                                              │
│   Nodes 2-30 receive alert, verify independently                            │
│                               ↓                                              │
│   Each agreeing node signs with BLS key                                     │
│                               ↓                                              │
│   Signatures aggregated (need 20 of 30 = 66.67%)                           │
│                               ↓                                              │
│   Threshold reached! Submit to chain                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. EXECUTION                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   SentinelRouter.executePauseWithAggregatedSignature()                      │
│                               ↓                                              │
│   Verify BLS signatures on-chain                                            │
│                               ↓                                              │
│   Call targetProtocol.pause() ← Protocol implements ISentinel               │
│                               ↓                                              │
│   SentinelShield.emergencyPauseAndClaim() → Bounty claim created            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. SETTLEMENT (48 hours later)                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Option A: No dispute filed                                                │
│             → Bounty auto-released to node                                  │
│             → Protocol saved from hack                                       │
│                                                                              │
│   Option B: Protocol disputes (false positive)                              │
│             → Oracle reviews evidence                                       │
│             → If false positive: Node slashed 10%, no bounty                │
│             → If real attack: Node gets bounty, protocol pays               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tokenomics ($SENTR)

### Staking Requirements

| Role | Minimum Stake | Purpose |
|------|---------------|---------|
| Node Operator | 10,000 $SENTR | Run validator node |
| Protocol (<$1M TVL) | 5,000 $SENTR | Get protection |
| Protocol ($1M-$10M) | 25,000 $SENTR | Get protection |
| Protocol ($10M-$100M) | 50,000 $SENTR | Get protection |
| Protocol (>$100M) | 100,000 $SENTR | Get protection |

### Incentives

| Action | Reward/Penalty |
|--------|----------------|
| Successful pause | Bounty: $5k-$100k (based on TVL) |
| Daily uptime | ~5 $SENTR block rewards |
| False positive | -10% stake slashed |
| Malicious behavior | -100% stake slashed |

---

## Implementation Status

| Component | Status | Tests |
|-----------|--------|-------|
| SentinelToken | ✅ Complete | 27 tests |
| SentinelRegistry | ✅ Complete | 29 tests |
| SentinelRouter | ✅ Complete | 19 tests |
| SentinelShield | ✅ Complete | 24 tests |
| Feature Extractors | ✅ Complete | Unit tests |
| Isolation Forest | ✅ Complete | Benchmarked |
| gRPC Server | ✅ Complete | Integration |
| Go Node (mempool) | ✅ Complete | - |
| Go Node (consensus) | ✅ Complete | Fixed auth |
| Docker Compose | ✅ Complete | - |

**Total: 99 smart contract tests passing**

---

## Security Fixes Applied

1. **RequestID consistency** - Events now use same ID throughout lifecycle
2. **Threshold rounding** - Uses ceiling division (harder to game)
3. **Race condition** - Check `executed` before processing, mark before external calls
4. **Gas limit** - `pause{gas: 100000}()` prevents DOS
5. **Message authentication** - Gossip validates sender is registered node
6. **Memory leak** - Stale peers deleted after 5 minutes

---

## Running the Project

### Prerequisites
- Go 1.22+
- Python 3.11+
- Foundry (forge)
- Docker & Docker Compose

### Smart Contract Tests
```bash
cd packages/sentinel-core
forge test
```

### Docker Deployment
```bash
docker compose up -d sentinel-brain sentinel-node
```

### Full Stack (with monitoring)
```bash
docker compose --profile full --profile monitoring up -d
```

---

## Remaining Work

### High Priority (Before Mainnet)
- [ ] BLS curve point validation in BLSVerifier.sol
- [ ] Error recovery when inference server fails
- [ ] Formal security audit

### Medium Priority
- [ ] Input validation in gRPC server
- [ ] Logging for dropped transactions
- [ ] PostgreSQL persistence backend

---

## References

- [Halborn - DeFi Hacks 2024](https://www.halborn.com/blog/post/year-in-review-the-biggest-defi-hacks-of-2024)
- [ChainSec - DeFi Hacks Database](https://chainsec.io/defi-hacks/)
- [Exploit Registry](packages/sentinel-brain/src/sentinel_brain/data/exploits/registry.py) - 70+ exploits from 2022-2025

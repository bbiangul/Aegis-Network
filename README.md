<p align="center">
  <img src="https://i.ibb.co/m5ccDLJq/Generated-Image-January-19-2026-9-26-AM.jpg" alt="Aegis - The Guardian" width="200"/>
</p>

<h1 align="center">Aegis Network</h1>

<p align="center">
  <strong>AI-Powered DeFi Security Infrastructure</strong><br/>
  Detect and prevent hacks before they happen
</p>

<p align="center">
  <a href="#architecture">Architecture</a> •
  <a href="#tokenomics-sentr">Tokenomics</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="docs/DEPLOYMENT.md">Deployment</a>
</p>

---

## The Motivation: The $3 Billion Gap

In 2025 alone, **$3.4 Billion** was stolen in crypto exploits.

Traditional security relies on **Audits** (before deployment) and **Bounties** (after the hack). There is a critical gap in the middle: **Execution Time**.

| Attack Vector | 2025 Losses (Approx) | Status Quo Defense | Aegis Defense |
| :--- | :--- | :--- | :--- |
| **Flash Loan / Math Logic** | ~$420M | None. (Auditors missed it) | **Interrupted.** (AI flags anomaly in mempool) |
| **Price Manipulation** | ~$150M | Reactive. (Oracle pauses too late) | **Pre-emptive.** (Checks CEX/DEX spread) |
| **Governance Attacks** | ~$200M | Time-Locks (Manual Veto) | **Automated.** (Simulates treasury drain) |

**Aegis exists to close this gap.** We don't just watch the chain; we defend it.

> *"Data based on 2025 on-chain forensic analysis [1](https://www.ainvest.com/news/irreversible-impact-hacks-crypto-projects-investor-trust-2601/) - [2](https://www.chainalysis.com/blog/crypto-hacking-stolen-funds-2026/) - [3](https://dig.watch/updates/crypto-theft-soars-in-2025-with-fewer-but-bigger-attacks)"*

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Aegis Network                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       │
│  │  sentinel-brain  │  │  sentinel-core   │  │  sentinel-node   │       │
│  │  (Python/ML)     │  │  (Solidity)      │  │  (Go)            │       │
│  │                  │  │                  │  │                  │       │
│  │  • AI Detection  │  │  • $SENTR Token  │  │  • Mempool       │       │
│  │  • Exploit Data  │  │  • Staking       │  │  • P2P Consensus │       │
│  │  • Feature Eng.  │  │  • Bounty System │  │  • BLS Signing   │       │
│  │  • Inference     │  │  • Kill Switch   │  │  • gRPC Bridge   │       │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Packages

| Package | Language | Description |
|---------|----------|-------------|
| **sentinel-brain** | Python | AI/ML anomaly detection using Isolation Forest |
| **sentinel-core** | Solidity | Smart contracts: token, staking, bounties, router |
| **sentinel-node** | Go | High-performance node: mempool, P2P, BLS signing |

---

## Tokenomics ($SENTR)

<p align="center">
  <img src="https://i.ibb.co/jPPJtHMR/Generated-Image-January-19-2026-9-52-AM.jpg" alt="SENTR Tokenomics" width="600"/>
</p>

### Token Distribution (100M Initial Supply)

| Allocation | Amount | Vesting |
|------------|--------|---------|
| **Team** | 20M (20%) | 4 years, 1 year cliff |
| **Investors** | 15M (15%) | 2 years, 6 month cliff |
| **Ecosystem** | 25M (25%) | 4 years, grants |
| **Treasury** | 25M (25%) | DAO-controlled |
| **Public** | 15M (15%) | TGE liquidity |

### Staking-for-Service Model

**Protocol Customers (TVL-based staking):**
| TVL Protected | Required Stake |
|---------------|----------------|
| < $1M         | 5,000 $SENTR   |
| $1M - $10M    | 25,000 $SENTR  |
| $10M - $100M  | 50,000 $SENTR  |
| > $100M       | 100,000 $SENTR |

**Node Operators:**
- Minimum stake: 10,000 $SENTR
- 21-day unstake cooldown
- Slashable for false positives or downtime

### Bounty System

48-hour dispute window prevents gaming:

| Pool TVL   | Bounty Amount |
|------------|---------------|
| < $1M      | $5,000        |
| $1M-$10M   | $25,000       |
| $10M-$100M | $50,000       |
| > $100M    | $100,000 (cap)|

> See [TOKENOMICS.md](docs/TOKENOMICS.md) for full economic model and vesting details.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Go 1.22+
- Foundry (forge, anvil)

### Installation

```bash
# Clone repository
git clone https://github.com/bbiangul/Aegis-Network.git
cd aegis-network

# Install sentinel-brain
cd packages/sentinel-brain
pip install -e .

# Install sentinel-core dependencies
cd ../sentinel-core
forge install

# Build sentinel-node
cd ../sentinel-node
go build ./cmd/sentinel
```

### Running Tests

```bash
# Python tests (64 tests)
cd packages/sentinel-brain && pytest

# Solidity tests (130 tests)
cd packages/sentinel-core && forge test

# Go tests
cd packages/sentinel-node && go test ./...
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and component details |
| [TOKENOMICS.md](docs/TOKENOMICS.md) | Full economic model with diagrams |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Testnet/mainnet deployment guide |
| [GAS_ECONOMICS.md](docs/GAS_ECONOMICS.md) | Who pays gas and when |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

---

## Contributing

We welcome contributions from the community! Whether it's bug fixes, new features, documentation improvements, or security research - all contributions are appreciated.

Check out our [CONTRIBUTING.md](CONTRIBUTING.md) guide to get started. If you have questions, feel free to open a GitHub Discussion or reach out at `biangulo43@gmail.com`.

---

## License

MIT License - See [LICENSE](LICENSE) for details.

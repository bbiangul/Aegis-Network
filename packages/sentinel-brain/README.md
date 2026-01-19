# Sentinel Brain

AI/ML component for DeFi exploit detection. Part of the Sentinel Protocol infrastructure.

## Overview

Sentinel Brain provides the intelligence layer for detecting malicious transactions before they're confirmed on-chain. It combines:

- **Historical Exploit Analysis**: Registry of 70+ known exploits from 2020-2025
- **Feature Extraction**: Multi-dimensional analysis of transaction traces
- **Anomaly Detection**: Isolation Forest model trained on exploit patterns
- **Real-time Inference**: Sub-300ms detection pipeline

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Inference Engine                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  Heuristic   │───▶│   Feature    │───▶│  Isolation   │          │
│  │   Filter     │    │  Extraction  │    │    Forest    │          │
│  │   (~5ms)     │    │   (~20ms)    │    │   (~30ms)    │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│     95% SAFE           Features:            Score:                  │
│     (filtered)       - Flash loan         0.0 - 1.0                 │
│                      - State delta        (anomaly)                 │
│                      - Bytecode sim                                 │
│                      - Opcode freq                                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
cd packages/sentinel-brain
pip install -e .
```

## Usage

### Exploit Registry

```python
from sentinel_brain.data.exploits import ExploitRegistry, AttackVector, Detectability

registry = ExploitRegistry()

# Get all trainable exploits (HIGH or MEDIUM detectability)
trainable = registry.get_trainable()
print(f"Trainable exploits: {len(trainable)}")

# Get flash loan attacks
flash_loans = registry.get_by_attack_vector(AttackVector.FLASH_LOAN)
for exploit in flash_loans:
    print(f"{exploit.protocol}: ${exploit.amount_millions}M")

# Get specific exploit details
euler = registry.get("euler_2023")
print(f"Block: {euler.block_number}, Tx: {euler.tx_hash}")
```

### Feature Extraction

```python
from sentinel_brain.features.extractors import (
    FlashLoanExtractor,
    StateVarianceExtractor,
    OpcodeExtractor,
)
from sentinel_brain.features.aggregator import FeatureAggregator

aggregator = FeatureAggregator([
    FlashLoanExtractor(),
    StateVarianceExtractor(),
    OpcodeExtractor(),
])

features = await aggregator.extract(transaction_trace)
```

### Inference

```python
from sentinel_brain.inference.engine import InferenceEngine

engine = InferenceEngine.load("models/isolation_forest.joblib")

result = await engine.analyze(pending_tx)
if result.is_suspicious:
    print(f"ALERT: Score {result.anomaly_score:.2f}")
```

## Data Sources

### Exploit Registry

The registry contains 70+ documented exploits from 2020-2025:

| Year | Count | Total Lost | Key Events |
|------|-------|------------|------------|
| 2022 | 20+   | $2B+       | Ronin, Wormhole, Nomad bridges |
| 2023 | 15+   | $1B+       | Euler, Curve (Vyper bug) |
| 2024 | 15+   | $1.5B+     | PlayDapp, Gala Games mints |
| 2025 | 9+    | $2B+       | Bybit, Cetus, Balancer v2 |

### Attack Vectors (Training Priority)

| Vector | Detectability | Priority |
|--------|---------------|----------|
| Flash Loan | HIGH | P0 |
| Oracle Manipulation | HIGH | P0 |
| Reentrancy | HIGH | P0 |
| Logic/Rounding Error | HIGH | P0 |
| Governance Attack | HIGH | P1 |
| Bridge Exploit | MEDIUM | P1 |
| Private Key Compromise | LOW | P2 |

## Feature Extractors

| Feature | Description | Significance |
|---------|-------------|--------------|
| Flash Loan Flag | Detects flashLoan() calls | Primary attack vector |
| State Change Variance | Storage slot deltas | >20% = suspicious |
| Bytecode Similarity | Jaccard to known exploits | Pattern matching |
| Opcode Frequency | DELEGATECALL, CREATE2 counts | Proxy/factory patterns |
| Contract Age | Deployment timestamp | <1 hour = high risk |
| Slippage Magnitude | Price impact analysis | Manipulation indicator |

## Model Details

### Isolation Forest

- **Training composition**: 90% benign, 10% anomalies
- **Features**: 15-dimensional vector
- **Output**: Anomaly score 0.0-1.0
- **Threshold**: 0.65 (configurable)

### Latency Budget

| Stage | Target | Notes |
|-------|--------|-------|
| Heuristic Filter | 5ms | Filters 95%+ safe txs |
| Simulation | 200ms | Anvil fork trace |
| Feature Extraction | 20ms | All extractors |
| ML Inference | 30ms | Isolation Forest |
| **Total** | **~255ms** | Within block time |

## Development

### Running Tests

```bash
cd packages/sentinel-brain
pytest tests/ -v
```

### Replaying Exploits

```bash
python scripts/replay_exploits.py --exploit euler_2023 --rpc $ETH_RPC_URL
```

### Training

```bash
python -m sentinel_brain.models.isolation_forest --train --data data/traces/
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ETH_RPC_URL` | Ethereum RPC endpoint | Yes |
| `ANVIL_PATH` | Path to Anvil binary | No (uses PATH) |
| `MODEL_PATH` | Trained model location | No (default: models/) |

## License

MIT License

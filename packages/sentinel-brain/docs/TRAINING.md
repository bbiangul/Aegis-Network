# Sentinel Brain - Model Training

## Overview

The Sentinel Brain uses an **Isolation Forest** model for anomaly detection. This unsupervised learning approach identifies transactions that deviate from normal patterns, making it effective for detecting novel attack vectors.

## Training Approach

### Semi-Supervised Learning

We use a semi-supervised approach:
1. **Train** on benign transactions only
2. **Test** on both benign and exploit transactions

This allows the model to learn what "normal" looks like, then flag anything that deviates as anomalous.

### Why Isolation Forest?

- **Speed**: Sub-30ms inference time
- **No labeled data required**: Learns from normal behavior
- **Novel attack detection**: Can catch zero-day exploits
- **Interpretable**: Feature contributions explain decisions

## Synthetic Training Data

Due to archive node requirements for historical replay, we generate synthetic training data based on known exploit patterns.

### Feature Vector (42 dimensions)

| Feature Group | Count | Description |
|---------------|-------|-------------|
| Flash Loan | 8 | Borrow amount, provider, repay ratio, callbacks |
| State Variance | 10 | Storage changes, balance deltas, variance ratio |
| Bytecode | 10 | Opcode frequencies, contract patterns, proxy detection |
| Opcode | 14 | CALL, DELEGATECALL, CREATE2, depth, gas ratio |

### Exploit Patterns Modeled (11 types)

| Attack Type | Detection Signal |
|-------------|-----------------|
| Flash Loan Attack | High borrow amount, single-tx repay |
| Oracle Manipulation | Large price impact, DEX interaction |
| Reentrancy | High CALL count, state changes mid-execution |
| Logic Error | Unusual balance ratios, edge case values |
| Governance Attack | Flash loan + governance function calls |
| Arithmetic Overflow | Extreme value ranges, precision loss |
| Donation Attack | Manipulation of share/asset ratios |
| Approval Exploit | Token allowance manipulation |
| Rounding Error | Interest calculation anomalies |
| Mint Vulnerability | Unauthorized token minting patterns |
| Compiler Bug | Vyper-style reentrancy signatures |

## Training Configuration

```bash
python scripts/train_model.py \
  --benign 1500 \
  --exploits 200 \
  --test-split 0.2 \
  --contamination 0.05 \
  --threshold 0.49 \
  --seed 42
```

| Parameter | Value | Description |
|-----------|-------|-------------|
| `benign` | 1500 | Normal transaction samples |
| `exploits` | 200 | Attack pattern samples |
| `test_split` | 0.2 | 20% held out for testing |
| `contamination` | 0.05 | Expected anomaly rate in production |
| `threshold` | 0.49 | Anomaly score cutoff |
| `seed` | 42 | Reproducibility |
| `attack_patterns` | 11 | Number of exploit types modeled |

## Benchmark Results

### Current Model Performance (v2)

| Metric | Value | Notes |
|--------|-------|-------|
| **Accuracy** | 95.75% | Overall correctness |
| **Precision** | 85.47% | True positives / predicted positives |
| **Recall** | 100.00% | Catches all exploits |
| **F1 Score** | 92.17% | Harmonic mean |

### Confusion Matrix

```
                 Predicted
              Benign   Exploit
Actual  Benign   283      17
       Exploit    0      100
```

- **True Positives**: 100 (all exploits detected)
- **True Negatives**: 283
- **False Positives**: 17 (benign flagged as exploit)
- **False Negatives**: 0 (no missed exploits)

### Model Evolution

| Version | Accuracy | Precision | Recall | F1 | False Positives |
|---------|----------|-----------|--------|-----|-----------------|
| v1 (baseline) | 77.83% | 49.50% | 100% | 66.23% | 51 |
| v2 (current) | 95.75% | 85.47% | 100% | 92.17% | 17 |

### Interpretation

The model prioritizes **recall** (catching exploits) over precision. This is intentional for a security system:

- **100% recall** = No exploit goes undetected
- **85.47% precision** = Low false alarm rate

In production, false positives trigger additional analysis rather than immediate pauses.

## Files

| File | Purpose |
|------|---------|
| `scripts/generate_training_data.py` | Synthetic data generator (11 patterns) |
| `scripts/train_model.py` | Training pipeline |
| `scripts/validate_real_traces.py` | Real exploit validation |
| `models/sentinel_model.joblib` | Trained model artifact |
| `models/training_results.json` | Benchmark metrics |
| `models/training_results_backup_v1.json` | v1 baseline metrics |

## Running Training

```bash
cd packages/sentinel-brain

# Install dependencies
uv sync

# Generate data and train
uv run python scripts/train_model.py

# Custom configuration
uv run python scripts/train_model.py \
  --benign 2000 \
  --exploits 200 \
  --threshold 0.6
```

## Real Exploit Validation

Successfully validated model on 5 historical exploits with **100% detection rate**:

| Exploit | Year | Amount | Attack Vector | Anomaly Score | Detected |
|---------|------|--------|---------------|---------------|----------|
| Beanstalk Farms | 2022 | $182M | Flash Loan + Governance | 0.5445 | YES |
| Euler Finance | 2023 | $197M | Flash Loan + Donation | 0.5246 | YES |
| Curve Finance | 2023 | $73.5M | Vyper Reentrancy | 0.5149 | YES |
| Harvest Finance | 2020 | $34M | Flash Loan + Oracle | 0.5281 | YES |
| Rari Capital | 2022 | $80M | Reentrancy | 0.5281 | YES |

### Log-Based Feature Extraction

Since public RPCs don't provide debug APIs for call tracing, we implemented log-based feature extraction:

**Flash Loan Detection** (from event logs):
- Aave V2/V3 FlashLoan events
- Balancer FlashLoan events
- dYdX FlashLoan events

**State Variance Estimation** (from Transfer events):
- Count of ERC20 Transfer events
- Maximum transfer amount
- Unique contracts involved

**Opcode Estimation** (from log addresses):
- Unique contract addresses = estimated call count
- High gas usage correlation

### Archive RPC Limitations

Full call tracing requires debug APIs (not available on public RPCs):
- **Available**: Transaction receipt, logs, gas used
- **Not Available**: Call trace, opcode counts, storage diffs

For complete trace data, use:
- Alchemy/Infura with archive access
- Self-hosted archive node with debug APIs

## Future Improvements

1. ~~**Log-based feature extraction** for better coverage~~ DONE
2. ~~**Threshold tuning** to reduce false positives~~ DONE
3. **Real exploit replay** with archive node access (debug APIs)
4. **Ensemble methods** combining multiple models
5. **Online learning** for continuous improvement
6. **L2 support** for Arbitrum, Optimism, Blast exploits

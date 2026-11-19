# Sentinel Core

Solidity smart contracts for the Sentinel Protocol. These contracts manage staking, bounties, and the kill switch mechanism for DeFi protection.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SentinelRouter                          │
│  - Receives BLS-signed pause requests                       │
│  - Verifies 20/30 threshold                                 │
│  - Calls target.pause()                                     │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│SentinelRegistry│    │SentinelShield │    │ BLSVerifier   │
│- Node staking │    │- Bounty vault │    │- Sig verify   │
│- Protocol reg │    │- Dispute logic│    │- Aggregation  │
│- Slashing     │    │- Payout tiers │    │               │
└───────────────┘    └───────────────┘    └───────────────┘
        │
        ▼
┌───────────────┐
│ SentinelToken │
│ ($SENTR)      │
│- Dynamic      │
│  rewards      │
└───────────────┘
```

## Contracts

### SentinelToken ($SENTR)

ERC20 utility token with dynamic reward mechanism.

**Key Features:**
- Max supply: 1 billion tokens
- Initial supply: 100 million tokens
- Dynamic daily rewards based on inverse square root formula

**Reward Formula:**
```
daily_reward = max(5, 50 / sqrt(total_staked_tvl_in_millions))
```

| Total Staked TVL | Daily Reward per Node |
|------------------|----------------------|
| $250K            | 100 SENTR            |
| $1M              | 50 SENTR             |
| $4M              | 25 SENTR             |
| $25M             | 10 SENTR             |
| $100M+           | 5 SENTR (minimum)    |

### SentinelRegistry

Manages node and protocol registration, staking, and slashing.

**Node Requirements:**
- Minimum stake: 10,000 SENTR
- BLS public key required for signature verification
- 21-day cooldown for unstaking

**Protocol Staking Tiers:**
| TVL Protected | Required Stake |
|---------------|----------------|
| < $1M         | 5,000 SENTR    |
| $1M - $10M    | 25,000 SENTR   |
| $10M - $100M  | 50,000 SENTR   |
| > $100M       | 100,000 SENTR  |

**Slashing Conditions:**
| Offense | Slash Amount |
|---------|--------------|
| False positive | 10% |
| Extended downtime | 5% |
| Malicious behavior | 100% |

### SentinelShield

Bounty vault with optimistic verification system.

**Workflow:**
1. Protocol deposits bounty into escrow
2. Node detects hack → triggers pause → claim pending
3. 48-hour dispute window
4. If undisputed: bounty auto-releases
5. If disputed + guilty: 0 bounty + stake slashed

**Bounty Tiers:**
| Pool TVL   | Bounty Amount |
|------------|---------------|
| < $1M      | $5,000        |
| $1M-$10M   | $25,000       |
| $10M-$100M | $50,000       |
| > $100M    | $100,000 (cap)|

### SentinelRouter

Kill switch executor with BLS signature verification.

**Key Features:**
- 20/30 signature threshold (configurable)
- Minimum 5 signers required
- 1-hour pause cooldown per protocol
- Aggregated BLS signature verification

### BLSVerifier

On-chain BLS signature verification using BN254 curve.

**Capabilities:**
- Single signature verification
- Aggregated signature verification
- Public key aggregation
- Hash-to-curve (G1)

### AegisSafeGuard (prototype)

Transaction guard for Safe treasuries, in `src/guard/`. It is independent of the token, registry and BLS
contracts above. It checks what a transaction did to the Safe, not what its calldata claims.

| Layer | What it does | Depends on |
|-------|--------------|------------|
| 1. Invariants | After each execution: singleton, owners, threshold, modules, guard, fallback handler and the guard's own policy must be unchanged; net outflow of each tracked asset must fit a refilling budget. Delegatecalls (except a parsed MultiSend batch), approvals and gas refunds are never routine. | Nothing off-chain |
| 2. Delay queue | Anything outside layer 1 reverts unless the Safe scheduled that exact action `delay` earlier. `vetoQuorum` owners can cancel it. | Someone watching `ActionScheduled` |
| 3. Attester (optional) | Can shorten a pending delay to `expeditedDelay`, or zero the budget for at most 24h with a 24h cooldown. Cannot approve, block permanently or move funds. | `IAttester` (k-of-n ECDSA in `ThresholdAttester`) |

If the attester is offline or fully compromised, the worst case is waiting out the normal delay.

**Known limits**

- **ERC-1271 permits bypass any guard.** With the default fallback handler, owner signatures validate
  off-chain messages, so a key thief can sign a permit for a token that accepts contract signatures and never
  send a Safe transaction. `forbidFallbackHandler` requires the Safe to have none. See
  `test_knownGap_erc1271PermitBypassesTheGuard`.
- **Only tracked assets are budgeted** (max 16). Other tokens, NFTs and DeFi positions are not.
- **Approval detection is by selector** (`approve`, `increaseAllowance`, `setApprovalForAll`, Permit2
  `approve`). A token with a non-standard approval function is not caught.
- **The budget is still spendable by a thief**, once per window.
- **Full threshold compromise is only delayed.** A thief who schedules a drain is stopped only if an owner
  vetoes in time. With `vetoQuorum = 1` a single hostile owner can in turn block every out-of-envelope
  action, including their own removal.
- **Safe 1.4.1 modules skip guards.** Enabling a module changes the fingerprint and needs the delay; a module
  enabled before the guard is installed is not constrained.
- **Unaudited prototype.** Per-transaction context uses regular storage (transient storage would be cheaper).

Tests run against the real Safe v1.4.1 contracts vendored in `lib/safe-smart-account`:

```bash
forge test --match-path test/AegisSafeGuard.t.sol
```

## Installation

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Install dependencies
cd packages/sentinel-core
forge install

# Build
forge build

# Test
forge test -vvv
```

## Deployment

```bash
# Deploy to local Anvil
anvil &
forge script script/Deploy.s.sol --rpc-url http://localhost:8545 --broadcast

# Deploy to testnet
forge script script/Deploy.s.sol --rpc-url $SEPOLIA_RPC_URL --broadcast --verify
```

## Contract Addresses

### Mainnet
(Not yet deployed)

### Sepolia Testnet
(Not yet deployed)

## Integration

### For Protected Protocols

1. Implement `ISentinel` interface:

```solidity
import {ISentinel} from "sentinel-core/interfaces/ISentinel.sol";

contract MyProtocol is ISentinel {
    address public sentinelRouter;
    bool private _paused;

    modifier onlySentinel() {
        require(msg.sender == sentinelRouter, "Not sentinel");
        _;
    }

    function pause() external onlySentinel {
        _paused = true;
    }

    function unpause() external onlyOwner {
        _paused = false;
    }

    function paused() external view returns (bool) {
        return _paused;
    }
}
```

2. Register with SentinelRegistry:

```solidity
// Approve SENTR tokens
sentrToken.approve(address(registry), stakeAmount);

// Register protocol
registry.registerProtocol(stakeAmount, tvl, address(myProtocol));
```

3. Deposit bounty into SentinelShield:

```solidity
// Approve payment token (USDC)
usdc.approve(address(shield), bountyAmount);

// Deposit bounty
shield.depositBounty(bountyAmount);
```

### For Node Operators

1. Generate BLS key pair
2. Stake SENTR tokens:

```solidity
// Approve SENTR tokens
sentrToken.approve(address(registry), stakeAmount);

// Register node
registry.registerNode(stakeAmount, blsPublicKey);
```

3. Run sentinel-node software

## Security Considerations

- BLS signature verification uses BN254 precompiles
- Optimistic verification prevents false positive attacks
- Slashing mechanism provides economic security
- Multi-signature threshold prevents single-node attacks
- 21-day cooldown prevents stake-and-slash attacks

---

## Why Sentinel? Trustworthiness & Comparison

### Would Sentinel Have Caught Past Exploits?

We maintain a registry of 75+ historical exploits (2020-2025) and classify them by detectability:

| Detectability | Exploit Count | Example |
|---------------|---------------|---------|
| **HIGH** | 45+ | Flash loans, reentrancy, oracle manipulation |
| **MEDIUM** | 10+ | Bridge exploits, logic errors |
| **LOW** | 20+ | Private key compromise, hot wallet breach |

**Detection Benchmark Results** (from `scripts/benchmark_model.py`):

| Metric | Value |
|--------|-------|
| Attack Recall | **100%** (catches all attack types) |
| False Positive Rate | 19.8% (handled by 48h dispute window) |
| Inference Latency | 2.6ms mean, 3.2ms p99 |

**Detection by Attack Type:**
- Flash loan attacks: 100% (71/71)
- Reentrancy: 100% (37/37)
- Oracle manipulation: 100% (29/29)
- Price manipulation: 100% (24/24)
- Governance attacks: 100% (9/9)
- Infinite mint: 100% (6/6)

**Run the benchmark yourself:**

```bash
cd packages/sentinel-brain
source .venv/bin/activate  # or activate your virtualenv

# Generate synthetic benchmark data (if not exists)
python scripts/generate_synthetic_benchmark.py

# Run benchmark
python scripts/benchmark_model.py
```

### Sentinel vs. Traditional Auditors

| Aspect | Auditors | Sentinel |
|--------|----------|----------|
| **When** | Before deployment | Real-time |
| **Cost** | $50K-$500K upfront | Stake-based (recoverable) |
| **Speed** | Weeks | <300ms detection |
| **False Positive Cost** | N/A | Slashing (10% stake) |

**Why staking is better than upfront payment:**
- Auditors get paid regardless of hack outcome
- Stake creates skin-in-the-game for nodes
- Your stake is returned when you leave (minus slashing)

### Sentinel vs. Formal Verification

| Aspect | Formal Verification | Sentinel |
|--------|---------------------|----------|
| **Coverage** | Specified properties | Behavioral anomalies |
| **Economic attacks** | Hard to model | Detectable via simulation |
| **Zero-days** | Can't catch unknown | ML detects anomalies |
| **Cost** | $100K-$1M per contract | Shared via staking |

**Why formal verification isn't enough:**
- Curve's Vyper was "correct" but had compiler bug ($73.5M)
- Euler was audited but interaction attack worked ($197M)
- Beanstalk governance was deterministic but flash loans broke it ($182M)

### Trust Model

**You don't need to trust Sentinel:**
1. Open source ML model (audit the detection logic)
2. Multi-node consensus (20/30 must agree)
3. Economic guarantees (nodes have 10K+ SENTR at stake)
4. Dispute mechanism (48h window to challenge)
5. Protocol control (you can unpause anytime)

---

## Roadmap

- [x] Smart contracts (SentinelToken, Registry, Router, Shield)
- [x] ML detection pipeline (Isolation Forest + heuristics)
- [x] Node software (Go with gRPC bridge)
- [x] BLS signature aggregation
- [x] Testnet simulation (99 tests passing)
- [ ] Mainnet deployment
- [ ] Security audit
- [ ] **DAO Governance** - Decentralized protocol governance
- [ ] **Continuous Learning** - Daily model updates based on execution data
- [ ] **Governance Guard** - Specialized flash loan governance attack detection
- [ ] **Oracle Guard** - Price manipulation and oracle attack detection
- [ ] **Bridge Guard** - Cross-chain message validation and bridge exploit detection

---

## License

MIT License

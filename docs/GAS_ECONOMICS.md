# Aegis Network - Gas Economics

This document explains who pays for gas in different scenarios and the economic incentives.

## Overview

The Aegis Network uses a **"Pull Model"** for rewards and a **"Shared Cost"** model for pause events. Understanding these economics is crucial for node operators.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           GAS FLOW DIAGRAM                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  NODE REGISTRATION                    DAILY REWARDS                      │
│  ──────────────────                   ─────────────                      │
│  Node pays gas ────► registerNode()   Node pays gas ────► claimRewards() │
│                      (~150k gas)                          (~80k gas)     │
│                                       SENTR minted to node               │
│                                                                          │
│  PAUSE EVENT (Attack Detected)                                           │
│  ─────────────────────────────                                           │
│  Node1 pays ────► createPauseRequest() ─────────────────────────────────►│
│                   (~100k gas)                                            │
│  Node2 pays ────► signPauseRequest() ───────────────────────────────────►│
│                   (~50k gas)                                             │
│  Node3 pays ────► signPauseRequest() ───────────────────────────────────►│
│                   (~50k gas)                                             │
│  Node4 pays ────► signPauseRequest() ───────────────────────────────────►│
│                   (~50k gas)                                             │
│  Node5 pays ────► signPauseRequest() ── THRESHOLD MET ──► pause() + claim│
│                   (~200k gas)           Protocol paused!                 │
│                                                                          │
│  BOUNTY PAYOUT (After 48h)                                               │
│  ─────────────────────────                                               │
│  Anyone pays ────► processPayout() ──► Bounty distributed to all signers │
│                    (~150k gas)                                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Node Registration & Staking

### Who Pays: **Node Operator**

| Action | Function | Est. Gas | Est. Cost (@ 30 gwei) |
|--------|----------|----------|----------------------|
| Register Node | `registerNode()` | ~150,000 | ~0.0045 ETH |
| Increase Stake | `increaseNodeStake()` | ~80,000 | ~0.0024 ETH |
| Request Unstake | `requestNodeUnstake()` | ~50,000 | ~0.0015 ETH |
| Complete Unstake | `completeNodeUnstake()` | ~100,000 | ~0.003 ETH |

**Note**: These are one-time or infrequent costs. Node registration is typically done once.

---

## 2. Daily Rewards (Pull Model)

### Who Pays: **Node Operator**

```solidity
// From SentinelRegistry.sol
function claimRewards() external nonReentrant {
    // Node pays gas to call this
    uint256 pendingRewards = calculatePendingRewards(msg.sender);
    token.mint(msg.sender, pendingRewards);  // New tokens minted
}
```

| Action | Function | Est. Gas | Est. Cost (@ 30 gwei) |
|--------|----------|----------|----------------------|
| Claim Rewards | `claimRewards()` | ~80,000 | ~0.0024 ETH |

### How Rewards Work

1. Rewards accumulate based on:
   - Node's stake proportion: `nodeStake / totalNodeStake`
   - Time since last claim
   - Total protocol TVL (affects daily reward pool)

2. **Economic Calculation**:
   ```
   Daily Reward Pool = 50 SENTR / sqrt(TVL in millions)
   Node Share = (Node Stake / Total Node Stake) × Daily Pool
   ```

3. **Break-even Analysis** (example @ $1 SENTR, 30 gwei gas):
   - Claim cost: ~0.0024 ETH (~$6 @ $2500/ETH)
   - Need at least 6 SENTR reward to break even
   - **Recommendation**: Claim weekly or monthly, not daily

### Reward Claiming Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                   OPTIMAL CLAIM FREQUENCY                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Small Stake (10k SENTR)     → Claim monthly                    │
│  Medium Stake (50k SENTR)    → Claim weekly                     │
│  Large Stake (100k+ SENTR)   → Claim every few days             │
│                                                                  │
│  Formula: Claim when (Pending Rewards × Price) > (Gas Cost × 2) │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Pause Events (Shared Cost Model)

### Who Pays: **All Participating Nodes**

A pause requires multiple nodes to sign. Each signer pays their own gas.

```
PAUSE EVENT COST DISTRIBUTION
═════════════════════════════

Node 1 (Initiator):
  └─► createPauseRequest()   ~100,000 gas   ~0.003 ETH

Node 2-4 (Signers):
  └─► signPauseRequest()     ~50,000 gas    ~0.0015 ETH each

Node 5 (Final Signer - Triggers Execution):
  └─► signPauseRequest()     ~200,000 gas   ~0.006 ETH
      + _executePause()
      + shield.emergencyPauseAndClaim()

TOTAL COST: ~400,000 gas (~0.012 ETH @ 30 gwei)
SHARED BY: 5 nodes
AVERAGE PER NODE: ~80,000 gas (~0.0024 ETH)
```

### Why the Last Signer Pays More

When the signature threshold is met, the last signer's transaction also:
1. Calls `_executePause()`
2. Calls `protocol.pause()`
3. Calls `shield.emergencyPauseAndClaim()`

This is intentional - incentivizes being an early signer.

### Economic Incentive

| Actor | Gas Cost | Bounty Share | Net Profit |
|-------|----------|--------------|------------|
| Node 1 (Initiator) | ~0.003 ETH | 20% of bounty | Positive |
| Nodes 2-4 | ~0.0015 ETH each | 20% each | Positive |
| Node 5 (Executor) | ~0.006 ETH | 20% | Positive |

**Example**: For a $50,000 bounty with 5 signers:
- Each node gets: $10,000
- Gas cost: ~$15-30
- **Net profit: ~$9,970-9,985 per node**

---

## 4. Bounty Payout (After Dispute Window)

### Who Pays: **Anyone (typically a node)**

```solidity
// From SentinelShield.sol
function processPayout(uint256 claimId) external {
    // Anyone can call after 48h
    // Bounty distributed to all signers
}
```

| Action | Function | Est. Gas | Est. Cost (@ 30 gwei) |
|--------|----------|----------|----------------------|
| Process Payout | `processPayout()` | ~150,000 | ~0.0045 ETH |

### Who Should Call It?

- **Typically**: One of the signers calls it to trigger their payout
- **Incentive**: First caller pays gas but everyone gets paid
- **Alternative**: Protocol could implement a keeper bot

---

## 5. Protocol Registration

### Who Pays: **Protocol Team**

| Action | Function | Est. Gas | Est. Cost (@ 30 gwei) |
|--------|----------|----------|----------------------|
| Register Protocol | `registerProtocol()` | ~200,000 | ~0.006 ETH |
| Deposit Bounty | `depositBounty()` | ~80,000 | ~0.0024 ETH |
| Withdraw Bounty | `withdrawBounty()` | ~100,000 | ~0.003 ETH |

---

## 6. Gas Optimization Strategies

### For Node Operators

1. **Batch Claims**: Claim rewards less frequently
   ```
   Weekly claim: 4x gas savings vs daily
   Monthly claim: ~28x gas savings vs daily
   ```

2. **Gas Price Timing**: Submit transactions during low gas periods
   - Best times: Weekends, late night UTC
   - Use gas trackers: etherscan.io/gastracker

3. **Early Signing**: Sign pause requests early (less gas than being executor)

### For the Protocol (Future Improvements)

1. **Claim Aggregation**: Allow batch claiming for multiple nodes
2. **Gas Subsidies**: Protocol could subsidize pause execution gas
3. **L2 Deployment**: Deploy on Arbitrum/Optimism for lower gas

---

## 7. Cost Summary Table

| Action | Who Pays | Frequency | Est. Gas | Est. Cost |
|--------|----------|-----------|----------|-----------|
| Register Node | Node | Once | 150k | 0.0045 ETH |
| Claim Rewards | Node | Weekly/Monthly | 80k | 0.0024 ETH |
| Create Pause Request | Initiator Node | Per attack | 100k | 0.003 ETH |
| Sign Pause Request | Each Signer | Per attack | 50k | 0.0015 ETH |
| Execute Pause | Last Signer | Per attack | 200k | 0.006 ETH |
| Process Bounty | Anyone | Per attack | 150k | 0.0045 ETH |
| Register Protocol | Protocol | Once | 200k | 0.006 ETH |
| Deposit Bounty | Protocol | Periodic | 80k | 0.0024 ETH |

---

## 8. Economic Model Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     NODE OPERATOR ECONOMICS                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INCOME                              │  EXPENSES                         │
│  ──────                              │  ────────                         │
│  + Daily SENTR rewards (minted)      │  - Initial registration gas       │
│  + Bounty share from pauses          │  - Reward claim gas               │
│  + SENTR price appreciation          │  - Pause signing gas              │
│                                      │  - Server/infrastructure costs    │
│                                                                          │
│  BREAK-EVEN EXAMPLE (10k SENTR stake, $1 SENTR price):                  │
│  ─────────────────────────────────────────────────────                  │
│  Monthly rewards: ~150 SENTR ($150)                                     │
│  Monthly gas costs: ~$20 (4 claims + 2 pause events)                    │
│  Infrastructure: ~$50/month (VPS)                                       │
│  ─────────────────────────────                                          │
│  Net profit: ~$80/month                                                 │
│                                                                          │
│  + Bounties from successful pauses (variable, potentially $1000s)       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Future Improvements (Roadmap)

| Improvement | Description | Gas Savings |
|-------------|-------------|-------------|
| **L2 Deployment** | Deploy on Arbitrum/Optimism | 90-95% |
| **Batch Claims** | Claim for multiple periods at once | 50% |
| **Meta-transactions** | Gasless transactions via relayer | 100% (for users) |
| **Account Abstraction** | ERC-4337 smart accounts | Variable |

---

## 10. FAQ

**Q: What if I can't afford gas for a pause signature?**
A: You can skip signing, but you won't receive bounty share. Other nodes will still reach threshold.

**Q: Can I automate reward claims?**
A: Yes, use a keeper service (like Chainlink Automation) to claim when profitable.

**Q: What happens if gas spikes during an attack?**
A: The economic incentive (bounty) typically far exceeds gas costs. A $50k bounty justifies even $500 in gas.

**Q: Who pays for the protocol's pause() call?**
A: The last signing node pays this as part of execution. It's included in their gas cost.

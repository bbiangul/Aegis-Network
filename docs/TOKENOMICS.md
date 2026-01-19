# Aegis Network - Tokenomics & Economics

## Overview

The $SENTR token powers the Aegis Network's security infrastructure through a staking-for-service model that aligns incentives between node operators and protected protocols.

---

## Economic Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AEGIS NETWORK ECONOMICS                                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────────────┐
                                    │   $SENTR TOKEN   │
                                    │  (100M supply)   │
                                    └────────┬─────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│     PROTOCOL CUSTOMERS    │  │      NODE OPERATORS       │  │     TOKEN HOLDERS         │
│   (DeFi Protocols)        │  │   (Security Validators)   │  │   (Governance)            │
├───────────────────────────┤  ├───────────────────────────┤  ├───────────────────────────┤
│                           │  │                           │  │                           │
│  Stake $SENTR for         │  │  Stake $SENTR to run      │  │  Participate in DAO       │
│  protection coverage      │  │  validator nodes          │  │  governance votes         │
│                           │  │                           │  │                           │
│  TVL-based tiers:         │  │  Minimum: 10,000 $SENTR   │  │  Vote on:                 │
│  • <$1M    →  5k $SENTR   │  │  21-day unstake cooldown  │  │  • Slashing parameters    │
│  • $1-10M  → 25k $SENTR   │  │                           │  │  • Bounty tiers           │
│  • $10-100M→ 50k $SENTR   │  │  Earn:                    │  │  • New protocol approvals │
│  • >$100M  →100k $SENTR   │  │  • Daily block rewards    │  │  • Upgrades               │
│                           │  │  • Bounties from pauses   │  │                           │
└─────────────┬─────────────┘  └─────────────┬─────────────┘  └───────────────────────────┘
              │                              │
              │                              │
              ▼                              ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               SENTINEL REGISTRY                                          │
│                         (Staking & Node Management Contract)                             │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   ┌─────────────────────┐              ┌─────────────────────┐                          │
│   │  Protocol Stakes    │              │    Node Stakes      │                          │
│   │  ═══════════════    │              │    ═══════════════  │                          │
│   │  Locked until       │              │    Locked until     │                          │
│   │  unregistration     │              │    21-day cooldown  │                          │
│   │  + 21-day cooldown  │              │    completes        │                          │
│   └─────────────────────┘              └─────────────────────┘                          │
│                                                                                          │
│   Functions:                                                                             │
│   • registerNode(stake, blsKey)     • registerProtocol(stake, tvl, pauseTarget)        │
│   • claimRewards()                  • updateProtocolTVL(newTVL)                        │
│   • requestUnstake()                • slashNode(nodeAddress, percentage)               │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Reward & Bounty Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DAILY REWARDS (Pull Model)                                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                         ┌────────────────────────────┐
                         │    REWARD CALCULATION      │
                         │    ════════════════════    │
                         │                            │
                         │  daily_pool = 50 / √TVL   │
                         │  (TVL in millions)         │
                         │                            │
                         │  node_share = node_stake   │
                         │              ───────────   │
                         │              total_stake   │
                         └──────────────┬─────────────┘
                                        │
                                        ▼
    ┌───────────────────────────────────────────────────────────────────────────┐
    │                                                                           │
    │  TVL $250K  ────►  100 $SENTR/day pool  ────►  Node calls claimRewards() │
    │  TVL $1M    ────►   50 $SENTR/day pool  ────►  $SENTR minted to node     │
    │  TVL $4M    ────►   25 $SENTR/day pool                                   │
    │  TVL $25M   ────►   10 $SENTR/day pool       (Node pays gas ~0.0024 ETH) │
    │  TVL $100M+ ────►    5 $SENTR/day pool                                   │
    │                                                                           │
    └───────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           BOUNTY FLOW (Attack Detection)                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  PROTOCOL                    SENTINEL SHIELD                      NODE OPERATORS
  ════════                    ═══════════════                      ══════════════

     │                              │                                    │
     │  1. depositBounty()          │                                    │
     │  ─────────────────►          │                                    │
     │  ($50k USDC/ETH)             │                                    │
     │                              │                                    │
     │                         ┌────┴────┐                               │
     │                         │ BOUNTY  │                               │
     │                         │  VAULT  │                               │
     │                         │ $50,000 │                               │
     │                         └────┬────┘                               │
     │                              │                                    │
     │                              │         2. Attack detected!        │
     │                              │         ◄───────────────────────── │
     │                              │         emergencyPauseAndClaim()   │
     │                              │                                    │
     │                         ┌────┴────┐                               │
     │                         │ CLAIM   │                               │
     │                         │ PENDING │                               │
     │                         │ 48h     │                               │
     │                         └────┬────┘                               │
     │                              │                                    │
     │  3a. No dispute              │         3b. Dispute filed          │
     │      (Real attack)           │             (False positive)       │
     │                              │                                    │
     │                              ▼                                    │
     │                    ┌─────────────────────┐                        │
     │                    │    SETTLEMENT       │                        │
     │                    └─────────────────────┘                        │
     │                              │                                    │
     │              ┌───────────────┴───────────────┐                    │
     │              │                               │                    │
     │              ▼                               ▼                    │
     │    ┌─────────────────┐             ┌─────────────────┐           │
     │    │  NO DISPUTE     │             │  DISPUTED       │           │
     │    │  ───────────    │             │  ────────       │           │
     │    │                 │             │                 │           │
     │    │  After 48h:     │             │  Oracle reviews │           │
     │    │  Bounty auto-   │             │                 │           │
     │    │  released to    │◄────────────│  If guilty:     │           │
     │    │  signing nodes  │             │  • No bounty    │           │
     │    │                 │             │  • 10% slashed  │           │
     │    │  $10k per node  │             │                 │           │
     │    │  (5 signers)    │             │  If innocent:   │──────────►│
     │    └─────────────────┘             │  • Full bounty  │  $10k/node│
     │                                    └─────────────────┘           │
     │                                                                   │
```

---

## Bounty Tiers

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              BOUNTY TIER STRUCTURE                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    Protocol TVL at Pause Time              Bounty Amount           Per Node (5 signers)
    ══════════════════════════              ═════════════           ════════════════════

         < $1M                    ────►       $5,000                    $1,000
                                                 │
       $1M - $10M                 ────►      $25,000                    $5,000
                                                 │
      $10M - $100M                ────►      $50,000                   $10,000
                                                 │
         > $100M                  ────►     $100,000 (cap)             $20,000


    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │                                                                                 │
    │    EXAMPLE: $50M Protocol Hack Prevented                                       │
    │    ─────────────────────────────────────                                       │
    │                                                                                 │
    │    Bounty pool:     $50,000                                                    │
    │    Signing nodes:   5 (reached 67% threshold)                                  │
    │    Per node:        $10,000                                                    │
    │                                                                                 │
    │    Node costs:                                                                 │
    │    • Pause signature gas: ~$15                                                 │
    │    • Compute/infra:       ~$5                                                  │
    │    ─────────────────────────────                                               │
    │    Net profit per node:   ~$9,980                                              │
    │                                                                                 │
    └─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Slashing Mechanics

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              SLASHING CONDITIONS                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    OFFENSE                         PENALTY                 WHO TRIGGERS
    ═══════                         ═══════                 ════════════

    False Positive Pause            10% stake slashed       Protocol via dispute
    (Paused protocol without                                + Oracle confirmation
     real attack)
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  1,000 $SENTR │
                                   │   BURNED     │
                                   └──────────────┘

    Extended Downtime               5% stake slashed        Registry automated
    (Node offline >24h)                                     (future: keeper bot)


    Malicious Behavior              100% stake slashed      DAO governance vote
    (Collusion, fake alerts,                                + multisig execution
     intentional harm)
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │ 10,000 $SENTR │
                                   │   BURNED     │
                                   └──────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           ANTI-GAMING MECHANISMS                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    ATTACK VECTOR                   MITIGATION
    ═════════════                   ══════════

    "Firefighter Arsonist"          48-hour dispute window
    (Trigger pause, claim bounty)   Protocol can challenge
                                    Oracle verifies real attack

    Stake-and-Slash                 21-day unstake cooldown
    (Stake, attack, withdraw)       Can't withdraw during dispute

    Sybil Attack                    10,000 $SENTR minimum per node
    (Many fake nodes)               Economic barrier to entry

    Collusion                       67% threshold (20/30 nodes)
    (Nodes coordinate false pause)  Would need majority collusion
                                    + slashing risk for all
```

---

## Complete Economic Cycle

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           COMPLETE ECONOMIC CYCLE                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘


                              ┌─────────────────────┐
                              │    DeFi PROTOCOL    │
                              │    (Customer)       │
                              └──────────┬──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
           ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
           │ 1. STAKE       │   │ 2. DEPOSIT     │   │ 3. INTEGRATE   │
           │    $SENTR      │   │    BOUNTY      │   │    ISentinel   │
           │                │   │                │   │                │
           │ 25,000 $SENTR  │   │ $50,000 USDC   │   │ pause() func   │
           │ (for $5M TVL)  │   │ in Shield      │   │ in protocol    │
           └───────┬────────┘   └───────┬────────┘   └───────┬────────┘
                   │                    │                    │
                   └────────────────────┼────────────────────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │  SENTINEL REGISTRY  │
                              │  + SENTINEL SHIELD  │
                              └──────────┬──────────┘
                                         │
                                         │ Protocol now protected
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                          │
│                              NODE OPERATORS                                              │
│                                                                                          │
│    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐        │
│    │  NODE 1  │    │  NODE 2  │    │  NODE 3  │    │  NODE 4  │    │  NODE 5  │        │
│    │ 10k SENTR│    │ 10k SENTR│    │ 10k SENTR│    │ 10k SENTR│    │ 10k SENTR│        │
│    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘        │
│         │               │               │               │               │              │
│         └───────────────┴───────────────┴───────────────┴───────────────┘              │
│                                         │                                              │
│                                         ▼                                              │
│                               ┌─────────────────────┐                                  │
│                               │   MEMPOOL MONITOR   │                                  │
│                               │   + ML INFERENCE    │                                  │
│                               └──────────┬──────────┘                                  │
│                                          │                                             │
│                           ┌──────────────┴──────────────┐                              │
│                           │                             │                              │
│                           ▼                             ▼                              │
│                  ┌─────────────────┐           ┌─────────────────┐                     │
│                  │  NORMAL DAY     │           │  ATTACK DAY     │                     │
│                  │  ───────────    │           │  ──────────     │                     │
│                  │                 │           │                 │                     │
│                  │  Monitor TXs    │           │  Detect attack  │                     │
│                  │  No threats     │           │  Sign pause req │                     │
│                  │                 │           │  Collect sigs   │                     │
│                  │  Earn daily     │           │  Execute pause  │                     │
│                  │  rewards        │           │  Claim bounty   │                     │
│                  │  (~5 $SENTR)    │           │  ($10k+ each)   │                     │
│                  │                 │           │                 │                     │
│                  └─────────────────┘           └─────────────────┘                     │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   VALUE CREATED     │
                              │   ═════════════     │
                              │                     │
                              │   Protocol: Saved   │
                              │   from $50M hack    │
                              │                     │
                              │   Nodes: Earned     │
                              │   $50k bounty       │
                              │                     │
                              │   Network: Trust    │
                              │   + adoption        │
                              └─────────────────────┘
```

---

## Token Distribution (Implemented)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           $SENTR TOKEN DISTRIBUTION                                      │
│                              (TokenVesting.sol)                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    Initial Supply: 100,000,000 $SENTR
    Max Supply:   1,000,000,000 $SENTR (minted via rewards over time)


                        ┌─────────────────────────────────┐
                        │      INITIAL DISTRIBUTION       │
                        │         (100M $SENTR)           │
                        └─────────────────────────────────┘
                                        │
            ┌───────────────┬───────────┼───────────┬───────────────┐
            │               │           │           │               │
            ▼               ▼           ▼           ▼               ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ TEAM       │  │ INVESTORS  │  │ ECOSYSTEM  │  │ TREASURY   │  │ PUBLIC     │
     │ 20%        │  │ 15%        │  │ 25%        │  │ 25%        │  │ 15%        │
     │            │  │            │  │            │  │            │  │            │
     │ 20M $SENTR │  │ 15M $SENTR │  │ 25M $SENTR │  │ 25M $SENTR │  │ 15M $SENTR │
     │            │  │            │  │            │  │            │  │            │
     │ 4yr vest   │  │ 2yr vest   │  │ 4yr vest   │  │ No vesting │  │ No vesting │
     │ 1yr cliff  │  │ 6mo cliff  │  │ No cliff   │  │ Multisig   │  │ TGE        │
     │ Revocable  │  │ Locked     │  │ Revocable  │  │ DAO        │  │ Liquidity  │
     └────────────┘  └────────────┘  └────────────┘  └────────────┘  └────────────┘
            │               │               │
            ▼               ▼               ▼
     ┌─────────────────────────────────────────────────────────────────────────────┐
     │                         TokenVesting.sol                                    │
     │                                                                             │
     │   • createVestingSchedule(beneficiary, amount, start, cliff, duration)     │
     │   • release() - Beneficiary claims vested tokens                           │
     │   • revoke() - Owner can revoke revocable schedules                        │
     │   • Linear vesting after cliff period                                      │
     │                                                                             │
     │   Contract Instances:                                                       │
     │   ├── teamVesting      (20M, revocable)                                    │
     │   ├── investorVesting  (15M, non-revocable)                                │
     │   └── ecosystemVesting (25M, revocable, for grants)                        │
     └─────────────────────────────────────────────────────────────────────────────┘
```

### Vesting Schedule Details

| Allocation | Amount | Cliff | Vesting | Revocable | Contract |
|------------|--------|-------|---------|-----------|----------|
| **Team** | 20M (20%) | 1 year | 4 years linear | Yes | teamVesting |
| **Investors** | 15M (15%) | 6 months | 2 years linear | No | investorVesting |
| **Ecosystem** | 25M (25%) | None | 4 years linear | Yes | ecosystemVesting |
| **Treasury** | 25M (25%) | None | None (unlocked) | N/A | Gnosis Safe |
| **Public** | 15M (15%) | None | None (unlocked) | N/A | Direct transfer |

### Deployment Scripts

```bash
# 1. Deploy core contracts
forge script script/Deploy.s.sol:Deploy --rpc-url $RPC --broadcast

# 2. Deploy vesting and distribute tokens
forge script script/Deploy.s.sol:DeployVesting --rpc-url $RPC --broadcast

# 3. Add individual investors
INVESTOR_ADDRESS=0x... INVESTOR_AMOUNT=1000000000000000000000000 \
forge script script/Deploy.s.sol:AddInvestorVesting --rpc-url $RPC --broadcast
```

### Team Vesting Example (20M over 4 years, 1 year cliff)

```
    Tokens
    Released
       │
   20M │                                                    ═══════════ (100%)
       │                                              ══════
       │                                        ══════
       │                                  ══════
       │                            ══════
       │                      ══════
       │                ══════
       │          ══════
    5M │    ══════                                          (25% at cliff)
       │════
     0 │────────────────────────────────────────────────────────────────────
       │         │                                                     │
       │      CLIFF                                                 FULLY
       │     (1 year)                                               VESTED
       │    Nothing                                                (4 years)
       │    unlocks
       │
       └──── Year 1 ────┴──── Year 2 ────┴──── Year 3 ────┴──── Year 4 ────►
                        │                │                │                │
                    5M unlocked      10M total        15M total        20M total
                    (monthly from here: ~417K/month)
```

### Inflation (Block Rewards)

```
    Reward formula: daily_reward = max(5, 50 / sqrt(TVL_in_millions))

    Year 1:  ~18M $SENTR minted (high rewards, bootstrapping)
    Year 2:  ~12M $SENTR minted (decreasing as TVL grows)
    Year 3:  ~8M $SENTR minted
    Year 4+: ~5M $SENTR minted (approaching minimum rate)

    Note: Actual inflation depends on:
    • Number of active nodes claiming rewards
    • Total staked TVL (inverse sqrt formula)
    • Slashing/burning events (deflationary pressure)
```

---

## Summary

| Participant | Stakes | Earns | Risks |
|-------------|--------|-------|-------|
| **Protocol** | $SENTR (TVL-tiered) + Bounty deposit | Protection from hacks | Bounty paid on real attacks |
| **Node Operator** | 10,000 $SENTR minimum | Daily rewards + Bounties | Slashing for false positives |
| **Token Holder** | $SENTR | Governance rights + Appreciation | Token volatility |

The economic model creates a flywheel:
1. **Protocols stake** → More TVL protected → Higher network value
2. **Nodes earn** → More operators join → Better coverage
3. **Attacks prevented** → Trust grows → More protocols join

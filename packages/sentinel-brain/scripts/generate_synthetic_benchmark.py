#!/usr/bin/env python3
"""
Generate realistic synthetic benchmark data for ML model evaluation.

Approaches:
1. Real transaction base + attack mutations
2. Protocol-specific simulations (AMM, lending)
3. Statistical modeling from known distributions
"""

from __future__ import annotations

import json
import random
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum
from typing import Any

import numpy as np


class TxType(Enum):
    # Benign transaction types
    SIMPLE_TRANSFER = "simple_transfer"
    TOKEN_TRANSFER = "token_transfer"
    TOKEN_APPROVAL = "token_approval"
    DEX_SWAP = "dex_swap"
    DEX_ADD_LIQUIDITY = "dex_add_liquidity"
    DEX_REMOVE_LIQUIDITY = "dex_remove_liquidity"
    LENDING_DEPOSIT = "lending_deposit"
    LENDING_BORROW = "lending_borrow"
    LENDING_REPAY = "lending_repay"
    NFT_MINT = "nft_mint"
    NFT_TRANSFER = "nft_transfer"
    GOVERNANCE_VOTE = "governance_vote"
    STAKING = "staking"
    BRIDGE_DEPOSIT = "bridge_deposit"

    # Attack types
    FLASH_LOAN_ATTACK = "flash_loan_attack"
    ORACLE_MANIPULATION = "oracle_manipulation"
    REENTRANCY = "reentrancy"
    SANDWICH_ATTACK = "sandwich_attack"
    GOVERNANCE_ATTACK = "governance_attack"
    PRICE_MANIPULATION = "price_manipulation"
    DONATION_ATTACK = "donation_attack"
    INFINITE_MINT = "infinite_mint"


# Real-world distributions based on mainnet data analysis
# Values are (mean, std) for log-normal distributions or (p,) for bernoulli

BENIGN_DISTRIBUTIONS = {
    TxType.SIMPLE_TRANSFER: {
        "frequency": 0.15,  # 15% of transactions
        "gas_used": (21000, 0),  # Fixed gas
        "value_eth": (0.5, 2.0),  # Log-normal: median 0.5 ETH
        "call_count": (1, 0),
        "unique_contracts": (1, 0),
        "transfer_count": (0, 0),
    },
    TxType.TOKEN_TRANSFER: {
        "frequency": 0.25,
        "gas_used": (65000, 20000),
        "value_eth": (0, 0),
        "token_value_usd": (500, 3.0),  # Log-normal
        "call_count": (1, 0),
        "unique_contracts": (1, 0),
        "transfer_count": (1, 0),
    },
    TxType.DEX_SWAP: {
        "frequency": 0.20,
        "gas_used": (150000, 50000),
        "value_eth": (0.1, 2.5),
        "token_value_usd": (1000, 3.0),
        "call_count": (3, 2),
        "unique_contracts": (3, 1),
        "transfer_count": (2, 1),
        "price_impact_bps": (10, 20),  # Usually <50 bps
    },
    TxType.DEX_ADD_LIQUIDITY: {
        "frequency": 0.05,
        "gas_used": (200000, 50000),
        "value_eth": (1.0, 2.0),
        "token_value_usd": (5000, 2.5),
        "call_count": (4, 2),
        "unique_contracts": (3, 1),
        "transfer_count": (3, 1),
    },
    TxType.LENDING_DEPOSIT: {
        "frequency": 0.08,
        "gas_used": (250000, 80000),
        "value_eth": (0, 0),
        "token_value_usd": (10000, 2.5),
        "call_count": (3, 2),
        "unique_contracts": (2, 1),
        "transfer_count": (2, 1),
    },
    TxType.LENDING_BORROW: {
        "frequency": 0.05,
        "gas_used": (350000, 100000),
        "value_eth": (0, 0),
        "token_value_usd": (5000, 2.5),
        "call_count": (5, 3),
        "unique_contracts": (3, 1),
        "transfer_count": (2, 1),
        "health_factor": (1.5, 0.3),  # Normal: 1.2-2.0
    },
    TxType.NFT_MINT: {
        "frequency": 0.08,
        "gas_used": (150000, 80000),
        "value_eth": (0.05, 1.5),
        "call_count": (2, 1),
        "unique_contracts": (2, 1),
        "transfer_count": (1, 0),
    },
    TxType.GOVERNANCE_VOTE: {
        "frequency": 0.02,
        "gas_used": (100000, 30000),
        "value_eth": (0, 0),
        "call_count": (1, 0),
        "unique_contracts": (1, 0),
        "transfer_count": (0, 0),
    },
    TxType.STAKING: {
        "frequency": 0.07,
        "gas_used": (200000, 60000),
        "value_eth": (1.0, 2.0),
        "token_value_usd": (5000, 2.5),
        "call_count": (3, 1),
        "unique_contracts": (2, 1),
        "transfer_count": (2, 1),
    },
    TxType.BRIDGE_DEPOSIT: {
        "frequency": 0.05,
        "gas_used": (150000, 50000),
        "value_eth": (0.5, 2.0),
        "token_value_usd": (2000, 2.5),
        "call_count": (3, 2),
        "unique_contracts": (2, 1),
        "transfer_count": (2, 1),
    },
}

ATTACK_DISTRIBUTIONS = {
    TxType.FLASH_LOAN_ATTACK: {
        "frequency": 0.3,  # Among attacks
        "gas_used": (2000000, 1000000),  # High gas
        "flash_loan_amount_usd": (10_000_000, 1.5),  # Log-normal, large
        "call_count": (30, 15),  # Many calls
        "unique_contracts": (10, 5),
        "transfer_count": (20, 10),
        "has_callback": True,
        "price_impact_bps": (500, 300),  # Large price impact
    },
    TxType.ORACLE_MANIPULATION: {
        "frequency": 0.15,
        "gas_used": (1500000, 500000),
        "token_value_usd": (5_000_000, 1.5),
        "call_count": (20, 10),
        "unique_contracts": (8, 4),
        "transfer_count": (15, 8),
        "price_impact_bps": (1000, 500),  # Extreme price impact
        "uses_multiple_dexes": True,
    },
    TxType.REENTRANCY: {
        "frequency": 0.15,
        "gas_used": (3000000, 1500000),  # Very high gas (repeated calls)
        "token_value_usd": (1_000_000, 2.0),
        "call_count": (50, 30),  # Many repeated calls
        "call_depth": (15, 5),  # Deep call stack
        "unique_contracts": (5, 2),  # Few contracts, many calls
        "transfer_count": (30, 15),
    },
    TxType.SANDWICH_ATTACK: {
        "frequency": 0.20,
        "gas_used": (300000, 100000),
        "token_value_usd": (100_000, 2.0),
        "call_count": (5, 2),
        "unique_contracts": (3, 1),
        "transfer_count": (4, 2),
        "price_impact_bps": (100, 50),
        "is_frontrun": True,
    },
    TxType.GOVERNANCE_ATTACK: {
        "frequency": 0.05,
        "gas_used": (2500000, 1000000),
        "flash_loan_amount_usd": (50_000_000, 1.2),  # Very large
        "call_count": (25, 10),
        "unique_contracts": (8, 3),
        "transfer_count": (10, 5),
        "has_flash_loan": True,
        "has_governance_call": True,
    },
    TxType.PRICE_MANIPULATION: {
        "frequency": 0.10,
        "gas_used": (1000000, 400000),
        "token_value_usd": (2_000_000, 1.5),
        "call_count": (15, 8),
        "unique_contracts": (6, 3),
        "transfer_count": (10, 5),
        "price_impact_bps": (2000, 1000),
        "reserve_change_pct": (30, 15),  # >20% reserve change
    },
    TxType.DONATION_ATTACK: {
        "frequency": 0.03,
        "gas_used": (500000, 200000),
        "token_value_usd": (500_000, 2.0),
        "call_count": (10, 5),
        "unique_contracts": (4, 2),
        "transfer_count": (5, 3),
        "share_ratio_anomaly": True,
    },
    TxType.INFINITE_MINT: {
        "frequency": 0.02,
        "gas_used": (800000, 300000),
        "token_value_usd": (10_000_000, 1.5),
        "call_count": (8, 4),
        "unique_contracts": (3, 1),
        "transfer_count": (3, 2),
        "mint_amount_anomaly": True,
    },
}


@dataclass
class SyntheticTransaction:
    """Synthetic transaction with full feature set."""
    tx_type: str
    is_attack: bool

    # Basic features
    gas_used: int
    value_wei: int

    # Flash loan features
    has_flash_loan: bool
    flash_loan_amount: int
    flash_loan_providers: list[str]
    has_callback: bool
    nested_flash_loans: bool

    # State variance features
    storage_changes: int
    unique_contracts: int
    transfer_count: int
    large_value_changes: int
    max_value_delta: int
    variance_ratio: float

    # Opcode features
    total_calls: int
    call_depth: int
    delegatecall_count: int
    create2_count: int
    selfdestruct_count: int
    external_calls: int

    # Protocol-specific
    price_impact_bps: int
    reserve_change_pct: float
    health_factor: float

    def to_feature_vector(self) -> list[float]:
        """Convert to 43-dimensional feature vector matching model input."""
        return [
            # Flash loan (8)
            1.0 if self.has_flash_loan else 0.0,
            1.0 if self.has_flash_loan else 0.0,  # flash_loan_count
            float(len(self.flash_loan_providers)),
            float(self.flash_loan_amount) / 1e18,
            1.0 if self.has_callback else 0.0,
            1.0 if self.has_callback else 0.0,  # callback_count
            1.0 if self.nested_flash_loans else 0.0,
            1.0 if self.has_flash_loan else 0.0,  # repayment_detected

            # State variance (10)
            float(self.storage_changes),
            float(self.unique_contracts),
            float(self.storage_changes),  # slots_modified
            float(self.transfer_count),  # balance_changes
            float(self.large_value_changes),
            float(self.max_value_delta) / 1e18,
            float(self.max_value_delta) / 1e18 / max(self.storage_changes, 1),  # avg_delta
            self.variance_ratio,
            float(self.storage_changes) * 0.1,  # zero_to_nonzero estimate
            float(self.storage_changes) * 0.05,  # nonzero_to_zero estimate

            # Bytecode (11)
            float(self.gas_used) / 1000,  # bytecode_length proxy
            1.0,  # is_contract
            0.0,  # is_proxy
            1000.0,  # contract_age_blocks
            0.0,  # is_verified
            0.0,  # matches_exploit
            0.0,  # jaccard_similarity
            1.0 if self.selfdestruct_count > 0 else 0.0,
            1.0 if self.delegatecall_count > 0 else 0.0,
            1.0 if self.create2_count > 0 else 0.0,
            float(min(self.total_calls * 2, 50)),  # bc_unique_opcodes estimate

            # Opcode (14)
            float(self.total_calls),
            float(self.call_depth),
            float(self.delegatecall_count),
            0.0,  # staticcall_count
            0.0,  # create_count
            float(self.create2_count),
            float(self.selfdestruct_count),
            float(self.external_calls),
            float(self.total_calls - self.external_calls),  # internal_calls
            float(self.external_calls),
            min(float(self.total_calls), 5.0),  # unique_call_types
            float(self.transfer_count),  # value_transfers
            0.8 if self.gas_used > 500000 else 0.5,  # gas_ratio
            0.0,  # revert_count
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sample_lognormal(mean: float, sigma: float) -> float:
    """Sample from log-normal distribution."""
    if sigma == 0:
        return mean
    if mean <= 0:
        return 0
    mu = math.log(mean) - (sigma ** 2) / 2
    return random.lognormvariate(mu, sigma)


def sample_normal_positive(mean: float, std: float) -> float:
    """Sample from normal distribution, clipped to positive."""
    return max(0, random.gauss(mean, std))


def generate_benign_transaction(tx_type: TxType) -> SyntheticTransaction:
    """Generate a realistic benign transaction."""
    dist = BENIGN_DISTRIBUTIONS[tx_type]

    gas_mean, gas_std = dist["gas_used"]
    gas_used = int(sample_normal_positive(gas_mean, gas_std))

    value_mean, value_sigma = dist.get("value_eth", (0, 0))
    value_eth = sample_lognormal(value_mean, value_sigma) if value_mean > 0 else 0
    value_wei = int(value_eth * 1e18)

    call_mean, call_std = dist.get("call_count", (1, 0))
    total_calls = max(1, int(sample_normal_positive(call_mean, call_std)))

    contract_mean, contract_std = dist.get("unique_contracts", (1, 0))
    unique_contracts = max(1, int(sample_normal_positive(contract_mean, contract_std)))

    transfer_mean, transfer_std = dist.get("transfer_count", (0, 0))
    transfer_count = max(0, int(sample_normal_positive(transfer_mean, transfer_std)))

    # Benign transactions have low variance, small deltas
    token_value_mean, token_value_sigma = dist.get("token_value_usd", (0, 0))
    token_value = sample_lognormal(token_value_mean, token_value_sigma) if token_value_mean > 0 else 0
    max_value_delta = int(token_value * 1e18 / 2000)  # Convert to ETH-equivalent

    return SyntheticTransaction(
        tx_type=tx_type.value,
        is_attack=False,
        gas_used=gas_used,
        value_wei=value_wei,
        has_flash_loan=False,
        flash_loan_amount=0,
        flash_loan_providers=[],
        has_callback=False,
        nested_flash_loans=False,
        storage_changes=transfer_count + random.randint(0, 3),
        unique_contracts=unique_contracts,
        transfer_count=transfer_count,
        large_value_changes=0 if token_value < 100000 else random.randint(0, 2),
        max_value_delta=max_value_delta,
        variance_ratio=random.uniform(0.0, 0.3),
        total_calls=total_calls,
        call_depth=min(total_calls, random.randint(1, 3)),
        delegatecall_count=0,
        create2_count=0,
        selfdestruct_count=0,
        external_calls=unique_contracts,
        price_impact_bps=int(sample_normal_positive(*dist.get("price_impact_bps", (5, 10)))),
        reserve_change_pct=random.uniform(0, 2),
        health_factor=sample_normal_positive(*dist.get("health_factor", (1.8, 0.2))),
    )


def generate_attack_transaction(tx_type: TxType) -> SyntheticTransaction:
    """Generate a realistic attack transaction."""
    dist = ATTACK_DISTRIBUTIONS[tx_type]

    gas_mean, gas_std = dist["gas_used"]
    gas_used = int(sample_normal_positive(gas_mean, gas_std))

    call_mean, call_std = dist.get("call_count", (20, 10))
    total_calls = max(5, int(sample_normal_positive(call_mean, call_std)))

    contract_mean, contract_std = dist.get("unique_contracts", (5, 3))
    unique_contracts = max(2, int(sample_normal_positive(contract_mean, contract_std)))

    transfer_mean, transfer_std = dist.get("transfer_count", (10, 5))
    transfer_count = max(2, int(sample_normal_positive(transfer_mean, transfer_std)))

    # Attack-specific features
    has_flash_loan = tx_type in [
        TxType.FLASH_LOAN_ATTACK,
        TxType.GOVERNANCE_ATTACK,
        TxType.PRICE_MANIPULATION,
    ] or dist.get("has_flash_loan", False)

    flash_loan_mean, flash_loan_sigma = dist.get("flash_loan_amount_usd", (0, 0))
    flash_loan_usd = sample_lognormal(flash_loan_mean, flash_loan_sigma) if has_flash_loan else 0
    flash_loan_amount = int(flash_loan_usd * 1e18 / 2000)  # Convert to ETH-equivalent

    # Large value movements in attacks
    token_value_mean, token_value_sigma = dist.get("token_value_usd", (1_000_000, 2.0))
    token_value = sample_lognormal(token_value_mean, token_value_sigma)
    max_value_delta = int(token_value * 1e18 / 2000)

    # High variance in attacks
    variance_ratio = random.uniform(0.5, 2.0)

    # Call depth for reentrancy
    call_depth = max(3, int(sample_normal_positive(*dist.get("call_depth", (5, 3)))))
    if tx_type == TxType.REENTRANCY:
        call_depth = max(10, call_depth)

    return SyntheticTransaction(
        tx_type=tx_type.value,
        is_attack=True,
        gas_used=gas_used,
        value_wei=0,
        has_flash_loan=has_flash_loan,
        flash_loan_amount=flash_loan_amount,
        flash_loan_providers=["aave_v2"] if has_flash_loan else [],
        has_callback=has_flash_loan or dist.get("has_callback", False),
        nested_flash_loans=has_flash_loan and random.random() < 0.2,
        storage_changes=transfer_count + random.randint(5, 20),
        unique_contracts=unique_contracts,
        transfer_count=transfer_count,
        large_value_changes=max(3, int(transfer_count * 0.5)),
        max_value_delta=max_value_delta,
        variance_ratio=variance_ratio,
        total_calls=total_calls,
        call_depth=call_depth,
        delegatecall_count=random.randint(0, 3) if tx_type != TxType.REENTRANCY else random.randint(2, 8),
        create2_count=random.randint(0, 2),
        selfdestruct_count=1 if random.random() < 0.1 else 0,
        external_calls=unique_contracts + random.randint(0, 5),
        price_impact_bps=int(sample_normal_positive(*dist.get("price_impact_bps", (500, 300)))),
        reserve_change_pct=sample_normal_positive(*dist.get("reserve_change_pct", (20, 10))),
        health_factor=0.5 if tx_type == TxType.FLASH_LOAN_ATTACK else 1.0,
    )


def generate_benchmark_dataset(
    n_benign: int = 10000,
    n_attacks: int = 500,
    seed: int = 42,
) -> tuple[list[SyntheticTransaction], list[SyntheticTransaction]]:
    """Generate a benchmark dataset with realistic distributions."""
    random.seed(seed)
    np.random.seed(seed)

    # Generate benign transactions based on frequency distribution
    benign_types = list(BENIGN_DISTRIBUTIONS.keys())
    benign_weights = [BENIGN_DISTRIBUTIONS[t]["frequency"] for t in benign_types]

    benign_txs = []
    for _ in range(n_benign):
        tx_type = random.choices(benign_types, weights=benign_weights)[0]
        benign_txs.append(generate_benign_transaction(tx_type))

    # Generate attack transactions based on frequency distribution
    attack_types = list(ATTACK_DISTRIBUTIONS.keys())
    attack_weights = [ATTACK_DISTRIBUTIONS[t]["frequency"] for t in attack_types]

    attack_txs = []
    for _ in range(n_attacks):
        tx_type = random.choices(attack_types, weights=attack_weights)[0]
        attack_txs.append(generate_attack_transaction(tx_type))

    return benign_txs, attack_txs


def compute_dataset_statistics(txs: list[SyntheticTransaction]) -> dict[str, Any]:
    """Compute statistics for a dataset."""
    vectors = np.array([tx.to_feature_vector() for tx in txs])

    return {
        "count": len(txs),
        "feature_means": vectors.mean(axis=0).tolist(),
        "feature_stds": vectors.std(axis=0).tolist(),
        "type_distribution": {
            tx_type: sum(1 for tx in txs if tx.tx_type == tx_type)
            for tx_type in set(tx.tx_type for tx in txs)
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic benchmark data")
    parser.add_argument("--benign", type=int, default=10000, help="Number of benign transactions")
    parser.add_argument("--attacks", type=int, default=500, help="Number of attack transactions")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, default="data/synthetic_benchmark", help="Output directory")

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.benign} benign + {args.attacks} attack transactions...")
    benign_txs, attack_txs = generate_benchmark_dataset(
        n_benign=args.benign,
        n_attacks=args.attacks,
        seed=args.seed,
    )

    # Save transactions
    print("Saving transactions...")
    with open(output_dir / "benign_transactions.json", "w") as f:
        json.dump([tx.to_dict() for tx in benign_txs], f, indent=2)

    with open(output_dir / "attack_transactions.json", "w") as f:
        json.dump([tx.to_dict() for tx in attack_txs], f, indent=2)

    # Save feature vectors for direct model training
    benign_vectors = np.array([tx.to_feature_vector() for tx in benign_txs])
    attack_vectors = np.array([tx.to_feature_vector() for tx in attack_txs])

    np.save(output_dir / "benign_features.npy", benign_vectors)
    np.save(output_dir / "attack_features.npy", attack_vectors)

    # Compute and save statistics
    print("\nBenign transaction statistics:")
    benign_stats = compute_dataset_statistics(benign_txs)
    print(f"  Count: {benign_stats['count']}")
    print(f"  Type distribution: {benign_stats['type_distribution']}")

    print("\nAttack transaction statistics:")
    attack_stats = compute_dataset_statistics(attack_txs)
    print(f"  Count: {attack_stats['count']}")
    print(f"  Type distribution: {attack_stats['type_distribution']}")

    with open(output_dir / "statistics.json", "w") as f:
        json.dump({
            "benign": benign_stats,
            "attacks": attack_stats,
            "config": {
                "n_benign": args.benign,
                "n_attacks": args.attacks,
                "seed": args.seed,
            }
        }, f, indent=2)

    print(f"\nDataset saved to {output_dir}")
    print(f"  - benign_transactions.json ({len(benign_txs)} txs)")
    print(f"  - attack_transactions.json ({len(attack_txs)} txs)")
    print(f"  - benign_features.npy ({benign_vectors.shape})")
    print(f"  - attack_features.npy ({attack_vectors.shape})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Benchmark model with protocol filter to measure false positive reduction.

Simulates protocol context for synthetic transactions to test
how protocol-aware filtering improves precision.
"""

from __future__ import annotations

import json
import time
import random
from pathlib import Path
from collections import defaultdict

import numpy as np

from sentinel_brain.models.isolation_forest import IsolationForestDetector
from sentinel_brain.models.protocol_filter import (
    ProtocolFilter,
    Protocol,
    OperationType,
    OPERATION_BOUNDS,
)
from sentinel_brain.features.aggregator import AggregatedFeatures
from sentinel_brain.features.extractors.flash_loan import FlashLoanFeatures
from sentinel_brain.features.extractors.state_variance import StateVarianceFeatures
from sentinel_brain.features.extractors.bytecode import BytecodeFeatures
from sentinel_brain.features.extractors.opcode import OpcodeFeatures


# Map synthetic tx types to protocols and operations
TX_TYPE_TO_CONTEXT = {
    # Benign types
    "simple_transfer": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "token_transfer": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "dex_swap": (Protocol.UNISWAP_V2, OperationType.SWAP),
    "dex_add_liquidity": (Protocol.UNISWAP_V2, OperationType.ADD_LIQUIDITY),
    "lending_deposit": (Protocol.AAVE_V2, OperationType.DEPOSIT),
    "lending_borrow": (Protocol.AAVE_V2, OperationType.BORROW),
    "nft_mint": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "governance_vote": (Protocol.UNKNOWN, OperationType.GOVERNANCE),
    "staking": (Protocol.LIDO, OperationType.STAKE),
    "bridge_deposit": (Protocol.STARGATE, OperationType.BRIDGE),

    # Attack types - should NOT get protocol benefit
    "flash_loan_attack": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "oracle_manipulation": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "reentrancy": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "sandwich_attack": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "governance_attack": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "price_manipulation": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "donation_attack": (Protocol.UNKNOWN, OperationType.UNKNOWN),
    "infinite_mint": (Protocol.UNKNOWN, OperationType.UNKNOWN),
}


def features_from_vector(vector: np.ndarray, tx_data: dict) -> AggregatedFeatures:
    """Convert feature vector back to AggregatedFeatures for protocol filter."""
    # This is a simplified reconstruction - in production we'd have full features
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=vector[0] > 0.5,
            flash_loan_count=int(vector[1]),
            flash_loan_providers=["aave_v2"] if vector[0] > 0.5 else [],
            flash_loan_amounts=[int(vector[3] * 1e18)] if vector[3] > 0 else [],
            total_borrowed=int(vector[3] * 1e18),
            has_callback=vector[4] > 0.5,
            callback_selectors=[],
            nested_flash_loans=vector[6] > 0.5,
            repayment_detected=vector[7] > 0.5,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=int(vector[8]),
            unique_contracts_modified=int(vector[9]),
            unique_slots_modified=int(vector[10]),
            balance_slot_changes=int(vector[11]),
            large_value_changes=int(vector[12]),
            max_value_delta=int(vector[13] * 1e18),
            avg_value_delta=vector[14] * 1e18,
            variance_ratio=vector[15],
            zero_to_nonzero=int(vector[16]),
            nonzero_to_zero=int(vector[17]),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=int(vector[18] * 1000),
            bytecode_hash="",
            is_contract=vector[19] > 0.5,
            is_proxy=vector[20] > 0.5,
            proxy_type=None,
            contract_age_blocks=int(vector[21]),
            is_verified=vector[22] > 0.5,
            matches_known_exploit=vector[23] > 0.5,
            matched_exploit_id=None,
            jaccard_similarity=vector[24],
            has_selfdestruct=vector[25] > 0.5,
            has_delegatecall=vector[26] > 0.5,
            has_create2=vector[27] > 0.5,
            unique_opcodes=int(vector[28]),
        ),
        opcode=OpcodeFeatures(
            total_calls=int(vector[29]),
            call_depth=int(vector[30]),
            delegatecall_count=int(vector[31]),
            staticcall_count=int(vector[32]),
            create_count=int(vector[33]),
            create2_count=int(vector[34]),
            selfdestruct_count=int(vector[35]),
            call_count=int(vector[36]),
            internal_calls=int(vector[37]),
            external_calls=int(vector[38]),
            unique_call_types=int(vector[39]),
            call_value_transfers=int(vector[40]),
            gas_forwarded_ratio=vector[41],
            revert_count=int(vector[42]),
        ),
        metadata={"gas_used": tx_data.get("gas_used", 100000)},
    )


def main():
    data_dir = Path(__file__).parent.parent / "data" / "synthetic_benchmark"
    model_path = Path(__file__).parent.parent / "models" / "sentinel_model.joblib"

    if not data_dir.exists():
        print(f"Benchmark data not found at {data_dir}")
        print("Run: python scripts/generate_synthetic_benchmark.py first")
        return

    # Load data
    print("Loading benchmark data...")
    benign_features = np.load(data_dir / "benign_features.npy")
    attack_features = np.load(data_dir / "attack_features.npy")

    with open(data_dir / "benign_transactions.json") as f:
        benign_txs = json.load(f)

    with open(data_dir / "attack_transactions.json") as f:
        attack_txs = json.load(f)

    print(f"  Benign: {len(benign_features)}")
    print(f"  Attacks: {len(attack_features)}")

    # Load model and filter
    print(f"\nLoading model...")
    model = IsolationForestDetector.load(model_path)
    protocol_filter = ProtocolFilter()

    # Benchmark WITHOUT protocol filter
    print("\n" + "=" * 60)
    print("BENCHMARK: ML ONLY (No Protocol Filter)")
    print("=" * 60)

    benign_fp_no_filter = 0
    attack_tp_no_filter = 0

    for features in benign_features:
        result = model.predict_single(features)
        if result.is_anomaly:
            benign_fp_no_filter += 1

    for features in attack_features:
        result = model.predict_single(features)
        if result.is_anomaly:
            attack_tp_no_filter += 1

    print(f"\nBenign False Positives: {benign_fp_no_filter}/{len(benign_features)} ({100*benign_fp_no_filter/len(benign_features):.2f}%)")
    print(f"Attack True Positives: {attack_tp_no_filter}/{len(attack_features)} ({100*attack_tp_no_filter/len(attack_features):.2f}%)")

    # Benchmark WITH protocol filter
    print("\n" + "=" * 60)
    print("BENCHMARK: ML + Protocol Filter")
    print("=" * 60)

    benign_results = []
    attack_results = []

    # Process benign transactions
    for i, (features, tx_data) in enumerate(zip(benign_features, benign_txs)):
        tx_type = tx_data["tx_type"]
        protocol, operation = TX_TYPE_TO_CONTEXT.get(tx_type, (Protocol.UNKNOWN, OperationType.UNKNOWN))

        # Get ML score
        ml_result = model.predict_single(features)
        raw_score = ml_result.anomaly_score

        # Apply protocol filter
        agg_features = features_from_vector(features, tx_data)

        # Simulate having protocol context
        if protocol != Protocol.UNKNOWN:
            # Add protocol address to trace context
            filter_result = protocol_filter.filter(
                agg_features,
                raw_score,
                to_address="0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap router
                input_data="0x38ed1739",  # swapExactTokensForTokens
            )
        else:
            filter_result = protocol_filter.filter(agg_features, raw_score)

        adjusted_score = filter_result.adjusted_risk_score
        is_flagged = adjusted_score >= 0.49  # Same threshold as model

        benign_results.append({
            "tx_type": tx_type,
            "raw_score": raw_score,
            "adjusted_score": adjusted_score,
            "adjustment": filter_result.context.risk_adjustment,
            "protocol": protocol.value,
            "operation": operation.value,
            "is_flagged": is_flagged,
            "ml_flagged": ml_result.is_anomaly,
        })

    # Process attack transactions
    for i, (features, tx_data) in enumerate(zip(attack_features, attack_txs)):
        tx_type = tx_data["tx_type"]

        # Attacks don't get protocol context (unknown attacker contracts)
        ml_result = model.predict_single(features)
        raw_score = ml_result.anomaly_score

        agg_features = features_from_vector(features, tx_data)
        filter_result = protocol_filter.filter(agg_features, raw_score)

        adjusted_score = filter_result.adjusted_risk_score
        is_flagged = adjusted_score >= 0.49

        attack_results.append({
            "tx_type": tx_type,
            "raw_score": raw_score,
            "adjusted_score": adjusted_score,
            "adjustment": filter_result.context.risk_adjustment,
            "is_flagged": is_flagged,
            "ml_flagged": ml_result.is_anomaly,
        })

    # Calculate metrics with filter
    benign_fp_with_filter = sum(1 for r in benign_results if r["is_flagged"])
    attack_tp_with_filter = sum(1 for r in attack_results if r["is_flagged"])

    print(f"\nBenign False Positives: {benign_fp_with_filter}/{len(benign_results)} ({100*benign_fp_with_filter/len(benign_results):.2f}%)")
    print(f"Attack True Positives: {attack_tp_with_filter}/{len(attack_results)} ({100*attack_tp_with_filter/len(attack_results):.2f}%)")

    # Breakdown by transaction type
    print("\n" + "-" * 60)
    print("FALSE POSITIVE REDUCTION BY TRANSACTION TYPE")
    print("-" * 60)

    fp_by_type_before = defaultdict(int)
    fp_by_type_after = defaultdict(int)
    total_by_type = defaultdict(int)

    for r in benign_results:
        total_by_type[r["tx_type"]] += 1
        if r["ml_flagged"]:
            fp_by_type_before[r["tx_type"]] += 1
        if r["is_flagged"]:
            fp_by_type_after[r["tx_type"]] += 1

    print(f"\n{'Transaction Type':<25} {'Before':<12} {'After':<12} {'Reduction':<12}")
    print("-" * 60)

    for tx_type in sorted(total_by_type.keys()):
        before = fp_by_type_before[tx_type]
        after = fp_by_type_after[tx_type]
        total = total_by_type[tx_type]
        reduction = before - after
        before_pct = 100 * before / total if total > 0 else 0
        after_pct = 100 * after / total if total > 0 else 0

        print(f"{tx_type:<25} {before:>4} ({before_pct:>5.1f}%) {after:>4} ({after_pct:>5.1f}%) -{reduction:>4}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    fp_reduction = benign_fp_no_filter - benign_fp_with_filter
    fp_reduction_pct = 100 * fp_reduction / benign_fp_no_filter if benign_fp_no_filter > 0 else 0

    recall_preserved = attack_tp_with_filter == attack_tp_no_filter

    print(f"\nFalse Positives Reduced: {fp_reduction} ({fp_reduction_pct:.1f}% reduction)")
    print(f"Recall Preserved: {'YES' if recall_preserved else 'NO'}")

    if attack_tp_with_filter < attack_tp_no_filter:
        lost = attack_tp_no_filter - attack_tp_with_filter
        print(f"  WARNING: Lost {lost} attack detections!")

    # Final metrics
    total = len(benign_results) + len(attack_results)
    tp = attack_tp_with_filter
    tn = len(benign_results) - benign_fp_with_filter
    fp = benign_fp_with_filter
    fn = len(attack_results) - attack_tp_with_filter

    accuracy = (tp + tn) / total
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\nFinal Metrics (with Protocol Filter):")
    print(f"  Accuracy:  {100*accuracy:.2f}%")
    print(f"  Precision: {100*precision:.2f}%")
    print(f"  Recall:    {100*recall:.2f}%")
    print(f"  F1 Score:  {100*f1:.2f}%")

    # Save results
    results = {
        "without_filter": {
            "false_positives": benign_fp_no_filter,
            "true_positives": attack_tp_no_filter,
        },
        "with_filter": {
            "false_positives": benign_fp_with_filter,
            "true_positives": attack_tp_with_filter,
            "fp_reduction": fp_reduction,
            "fp_reduction_pct": fp_reduction_pct,
        },
        "final_metrics": {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
        },
    }

    output_path = Path(__file__).parent.parent / "models" / "protocol_filter_benchmark.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()

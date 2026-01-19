#!/usr/bin/env python3
"""
Benchmark model on synthetic data.

Tests:
1. Detection rate on attack vs benign
2. False positive / false negative rates
3. Latency distribution
4. Per-attack-type performance
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from collections import defaultdict

import numpy as np

from sentinel_brain.models.isolation_forest import IsolationForestDetector


def main():
    data_dir = Path(__file__).parent.parent / "data" / "synthetic_benchmark"
    model_path = Path(__file__).parent.parent / "models" / "sentinel_model.joblib"

    if not data_dir.exists():
        print(f"Benchmark data not found at {data_dir}")
        print("Run: python scripts/generate_synthetic_benchmark.py first")
        return

    if not model_path.exists():
        print(f"Model not found at {model_path}")
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

    # Load model
    print(f"\nLoading model from {model_path}")
    model = IsolationForestDetector.load(model_path)

    # Benchmark benign transactions
    print("\n" + "=" * 60)
    print("BENCHMARKING BENIGN TRANSACTIONS")
    print("=" * 60)

    benign_results = []
    benign_latencies = []

    for i, features in enumerate(benign_features):
        start = time.perf_counter()
        result = model.predict_single(features)
        latency = (time.perf_counter() - start) * 1000
        benign_latencies.append(latency)
        benign_results.append({
            "is_anomaly": result.is_anomaly,
            "score": result.anomaly_score,
            "tx_type": benign_txs[i]["tx_type"],
        })

    benign_fp = sum(1 for r in benign_results if r["is_anomaly"])
    benign_tn = len(benign_results) - benign_fp

    print(f"\nTrue Negatives: {benign_tn} ({100*benign_tn/len(benign_results):.2f}%)")
    print(f"False Positives: {benign_fp} ({100*benign_fp/len(benign_results):.2f}%)")

    # FP by transaction type
    print("\nFalse Positives by Transaction Type:")
    fp_by_type = defaultdict(int)
    total_by_type = defaultdict(int)
    for r in benign_results:
        total_by_type[r["tx_type"]] += 1
        if r["is_anomaly"]:
            fp_by_type[r["tx_type"]] += 1

    for tx_type in sorted(total_by_type.keys()):
        fp = fp_by_type[tx_type]
        total = total_by_type[tx_type]
        rate = 100 * fp / total if total > 0 else 0
        print(f"  {tx_type:<25} {fp:>4}/{total:<4} ({rate:.1f}%)")

    # Benchmark attack transactions
    print("\n" + "=" * 60)
    print("BENCHMARKING ATTACK TRANSACTIONS")
    print("=" * 60)

    attack_results = []
    attack_latencies = []

    for i, features in enumerate(attack_features):
        start = time.perf_counter()
        result = model.predict_single(features)
        latency = (time.perf_counter() - start) * 1000
        attack_latencies.append(latency)
        attack_results.append({
            "is_anomaly": result.is_anomaly,
            "score": result.anomaly_score,
            "tx_type": attack_txs[i]["tx_type"],
        })

    attack_tp = sum(1 for r in attack_results if r["is_anomaly"])
    attack_fn = len(attack_results) - attack_tp

    print(f"\nTrue Positives: {attack_tp} ({100*attack_tp/len(attack_results):.2f}%)")
    print(f"False Negatives: {attack_fn} ({100*attack_fn/len(attack_results):.2f}%)")

    # Detection by attack type
    print("\nDetection Rate by Attack Type:")
    tp_by_type = defaultdict(int)
    total_by_type = defaultdict(int)
    for r in attack_results:
        total_by_type[r["tx_type"]] += 1
        if r["is_anomaly"]:
            tp_by_type[r["tx_type"]] += 1

    for tx_type in sorted(total_by_type.keys()):
        tp = tp_by_type[tx_type]
        total = total_by_type[tx_type]
        rate = 100 * tp / total if total > 0 else 0
        status = "✓" if rate >= 80 else "⚠" if rate >= 50 else "✗"
        print(f"  {status} {tx_type:<25} {tp:>3}/{total:<3} ({rate:.1f}%)")

    # Overall metrics
    print("\n" + "=" * 60)
    print("OVERALL METRICS")
    print("=" * 60)

    total = len(benign_results) + len(attack_results)
    accuracy = (benign_tn + attack_tp) / total
    precision = attack_tp / (attack_tp + benign_fp) if (attack_tp + benign_fp) > 0 else 0
    recall = attack_tp / (attack_tp + attack_fn) if (attack_tp + attack_fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"\nAccuracy:  {100*accuracy:.2f}%")
    print(f"Precision: {100*precision:.2f}%")
    print(f"Recall:    {100*recall:.2f}%")
    print(f"F1 Score:  {100*f1:.2f}%")

    print(f"\nConfusion Matrix:")
    print(f"                 Predicted")
    print(f"              Benign   Attack")
    print(f"Actual Benign  {benign_tn:>5}    {benign_fp:>5}")
    print(f"       Attack  {attack_fn:>5}    {attack_tp:>5}")

    # Latency analysis
    print("\n" + "=" * 60)
    print("LATENCY ANALYSIS")
    print("=" * 60)

    all_latencies = benign_latencies + attack_latencies

    print(f"\nTotal Predictions: {len(all_latencies)}")
    print(f"Mean Latency:   {np.mean(all_latencies):.3f} ms")
    print(f"Median Latency: {np.median(all_latencies):.3f} ms")
    print(f"P95 Latency:    {np.percentile(all_latencies, 95):.3f} ms")
    print(f"P99 Latency:    {np.percentile(all_latencies, 99):.3f} ms")
    print(f"Max Latency:    {np.max(all_latencies):.3f} ms")

    # Score distribution
    print("\n" + "=" * 60)
    print("SCORE DISTRIBUTION")
    print("=" * 60)

    benign_scores = [r["score"] for r in benign_results]
    attack_scores = [r["score"] for r in attack_results]

    print(f"\nBenign Transactions:")
    print(f"  Mean:   {np.mean(benign_scores):.4f}")
    print(f"  Std:    {np.std(benign_scores):.4f}")
    print(f"  Min:    {np.min(benign_scores):.4f}")
    print(f"  Max:    {np.max(benign_scores):.4f}")

    print(f"\nAttack Transactions:")
    print(f"  Mean:   {np.mean(attack_scores):.4f}")
    print(f"  Std:    {np.std(attack_scores):.4f}")
    print(f"  Min:    {np.min(attack_scores):.4f}")
    print(f"  Max:    {np.max(attack_scores):.4f}")

    # Score separation
    threshold = model.threshold
    benign_above = sum(1 for s in benign_scores if s >= threshold)
    attack_below = sum(1 for s in attack_scores if s < threshold)

    print(f"\nThreshold: {threshold}")
    print(f"Benign above threshold: {benign_above} ({100*benign_above/len(benign_scores):.2f}%)")
    print(f"Attacks below threshold: {attack_below} ({100*attack_below/len(attack_scores):.2f}%)")

    # Save results
    results = {
        "metrics": {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "false_positive_rate": benign_fp / len(benign_results),
            "false_negative_rate": attack_fn / len(attack_results),
        },
        "confusion_matrix": {
            "true_negatives": benign_tn,
            "false_positives": benign_fp,
            "false_negatives": attack_fn,
            "true_positives": attack_tp,
        },
        "latency": {
            "mean_ms": float(np.mean(all_latencies)),
            "median_ms": float(np.median(all_latencies)),
            "p95_ms": float(np.percentile(all_latencies, 95)),
            "p99_ms": float(np.percentile(all_latencies, 99)),
        },
        "dataset": {
            "benign_count": len(benign_results),
            "attack_count": len(attack_results),
        },
    }

    output_path = Path(__file__).parent.parent / "models" / "benchmark_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()

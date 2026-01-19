#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sentinel_brain.models.isolation_forest import IsolationForestDetector
from generate_training_data import generate_training_data

logger = structlog.get_logger()


def train_and_evaluate(
    n_benign: int = 900,
    n_exploits: int = 100,
    test_split: float = 0.2,
    contamination: float = 0.05,
    threshold: float = 0.5,
    seed: int = 42,
) -> dict:
    X, y, metadata = generate_training_data(
        n_benign=n_benign,
        n_exploits=n_exploits,
        seed=seed,
    )

    np.random.seed(seed)

    benign_indices = np.where(y == 0)[0]
    exploit_indices = np.where(y == 1)[0]

    np.random.shuffle(benign_indices)
    np.random.shuffle(exploit_indices)

    benign_train_size = int(len(benign_indices) * (1 - test_split))
    exploit_test_size = int(len(exploit_indices) * test_split)

    train_indices = benign_indices[:benign_train_size]
    test_benign = benign_indices[benign_train_size:]
    test_exploit = exploit_indices[:max(exploit_test_size, len(exploit_indices) // 2)]

    test_indices = np.concatenate([test_benign, test_exploit])
    np.random.shuffle(test_indices)

    X_train, y_train = X[train_indices], y[train_indices]
    X_test, y_test = X[test_indices], y[test_indices]

    logger.info(
        "data_split",
        train_size=len(X_train),
        test_size=len(X_test),
        train_anomaly_rate=y_train.mean(),
        test_anomaly_rate=y_test.mean(),
    )

    detector = IsolationForestDetector(contamination=contamination, threshold=threshold)

    logger.info("training_model", contamination=contamination, threshold=threshold)
    detector.train(X_train)

    logger.info("evaluating_model")
    metrics = detector.evaluate(X_test, y_test)

    logger.info(
        "evaluation_results",
        accuracy=f"{metrics['accuracy']:.4f}",
        precision=f"{metrics['precision']:.4f}",
        recall=f"{metrics['recall']:.4f}",
        f1=f"{metrics['f1_score']:.4f}",
    )

    predictions = []
    for i, (x, label) in enumerate(zip(X_test, y_test)):
        result = detector.predict_single(x)
        predictions.append({
            "index": int(test_indices[i]),
            "true_label": int(label),
            "predicted": 1 if result.is_anomaly else 0,
            "anomaly_score": float(result.anomaly_score),
            "confidence": float(result.confidence),
            "metadata": metadata[test_indices[i]],
        })

    tp = sum(1 for p in predictions if p["true_label"] == 1 and p["predicted"] == 1)
    fp = sum(1 for p in predictions if p["true_label"] == 0 and p["predicted"] == 1)
    tn = sum(1 for p in predictions if p["true_label"] == 0 and p["predicted"] == 0)
    fn = sum(1 for p in predictions if p["true_label"] == 1 and p["predicted"] == 0)

    logger.info(
        "confusion_matrix",
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
    )

    return {
        "metrics": metrics,
        "predictions": predictions,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "train_size": len(X_train),
        "test_size": len(X_test),
        "detector": detector,
    }


def main():
    parser = argparse.ArgumentParser(description="Train Isolation Forest model")
    parser.add_argument("--benign", type=int, default=900, help="Number of benign samples")
    parser.add_argument("--exploits", type=int, default=100, help="Number of exploit samples")
    parser.add_argument("--test-split", type=float, default=0.2, help="Test split ratio")
    parser.add_argument("--contamination", type=float, default=0.05, help="Contamination rate")
    parser.add_argument("--threshold", type=float, default=0.5, help="Anomaly threshold")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, default="sentinel_model.joblib", help="Model output file")
    parser.add_argument("--results", type=str, default="training_results.json", help="Results output file")

    args = parser.parse_args()

    results = train_and_evaluate(
        n_benign=args.benign,
        n_exploits=args.exploits,
        test_split=args.test_split,
        contamination=args.contamination,
        threshold=args.threshold,
        seed=args.seed,
    )

    model_path = Path(args.output)
    results["detector"].save(str(model_path))
    logger.info("model_saved", path=str(model_path))

    results_path = Path(args.results)
    results_data = {
        "metrics": results["metrics"],
        "confusion_matrix": results["confusion_matrix"],
        "train_size": results["train_size"],
        "test_size": results["test_size"],
        "config": {
            "benign": args.benign,
            "exploits": args.exploits,
            "test_split": args.test_split,
            "contamination": args.contamination,
            "seed": args.seed,
        },
    }

    with open(results_path, "w") as f:
        json.dump(results_data, f, indent=2)
    logger.info("results_saved", path=str(results_path))

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Model saved to: {model_path}")
    print(f"Results saved to: {results_path}")
    print()
    print("Metrics:")
    print(f"  Accuracy:  {results['metrics']['accuracy']:.4f}")
    print(f"  Precision: {results['metrics']['precision']:.4f}")
    print(f"  Recall:    {results['metrics']['recall']:.4f}")
    print(f"  F1 Score:  {results['metrics']['f1_score']:.4f}")
    print()
    print("Confusion Matrix:")
    cm = results["confusion_matrix"]
    print(f"  True Positives:  {cm['tp']}")
    print(f"  False Positives: {cm['fp']}")
    print(f"  True Negatives:  {cm['tn']}")
    print(f"  False Negatives: {cm['fn']}")
    print("=" * 60)


if __name__ == "__main__":
    main()

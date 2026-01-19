from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import joblib
import structlog
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from sentinel_brain.features.aggregator import AggregatedFeatures, FeatureAggregator


logger = structlog.get_logger()


@dataclass
class DetectionResult:
    anomaly_score: float
    is_anomaly: bool
    confidence: float
    feature_contributions: dict[str, float]
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_score": self.anomaly_score,
            "is_anomaly": self.is_anomaly,
            "confidence": self.confidence,
            "feature_contributions": self.feature_contributions,
            "threshold": self.threshold,
        }


@dataclass
class TrainingMetrics:
    num_samples: int
    num_features: int
    contamination: float
    oob_score: float | None
    feature_importances: dict[str, float]


class IsolationForestDetector:
    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 100,
        max_samples: str | int = "auto",
        threshold: float = 0.65,
        random_state: int = 42,
    ):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.threshold = threshold
        self.random_state = random_state

        self.model: IsolationForest | None = None
        self.scaler: StandardScaler | None = None
        self.feature_names: list[str] = []
        self.is_trained = False

    def train(
        self,
        features: list[AggregatedFeatures] | np.ndarray,
        labels: list[int] | np.ndarray | None = None,
    ) -> TrainingMetrics:
        if isinstance(features, np.ndarray):
            if features.size == 0:
                raise ValueError("No features provided for training")
            X = features
        else:
            if len(features) == 0:
                raise ValueError("No features provided for training")
            X = np.stack([f.to_vector() for f in features])

        aggregator = FeatureAggregator()
        self.feature_names = aggregator.get_feature_names()

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            random_state=self.random_state,
            n_jobs=-1,
            warm_start=False,
        )

        self.model.fit(X_scaled)
        self.is_trained = True

        feature_importances = self._calculate_feature_importances(X_scaled)

        logger.info(
            "model_trained",
            num_samples=len(features),
            num_features=X.shape[1],
            contamination=self.contamination,
        )

        return TrainingMetrics(
            num_samples=len(features),
            num_features=X.shape[1],
            contamination=self.contamination,
            oob_score=None,
            feature_importances=feature_importances,
        )

    def predict(self, features: AggregatedFeatures) -> DetectionResult:
        if not self.is_trained or self.model is None or self.scaler is None:
            raise RuntimeError("Model not trained")

        X = features.to_vector().reshape(1, -1)
        X_scaled = self.scaler.transform(X)

        raw_score = self.model.decision_function(X_scaled)[0]
        anomaly_score = self._normalize_score(raw_score)

        is_anomaly = anomaly_score >= self.threshold
        confidence = self._calculate_confidence(anomaly_score)

        contributions = self._calculate_feature_contributions(X_scaled[0])

        return DetectionResult(
            anomaly_score=anomaly_score,
            is_anomaly=is_anomaly,
            confidence=confidence,
            feature_contributions=contributions,
            threshold=self.threshold,
        )

    def predict_single(self, feature_vector: np.ndarray) -> DetectionResult:
        if not self.is_trained or self.model is None or self.scaler is None:
            raise RuntimeError("Model not trained")

        X = feature_vector.reshape(1, -1)
        X_scaled = self.scaler.transform(X)

        raw_score = self.model.decision_function(X_scaled)[0]
        anomaly_score = self._normalize_score(raw_score)

        is_anomaly = anomaly_score >= self.threshold
        confidence = self._calculate_confidence(anomaly_score)

        contributions = self._calculate_feature_contributions(X_scaled[0])

        return DetectionResult(
            anomaly_score=anomaly_score,
            is_anomaly=is_anomaly,
            confidence=confidence,
            feature_contributions=contributions,
            threshold=self.threshold,
        )

    def predict_batch(self, features_list: list[AggregatedFeatures]) -> list[DetectionResult]:
        return [self.predict(f) for f in features_list]

    def predict_proba(self, features: AggregatedFeatures) -> tuple[float, float]:
        result = self.predict(features)
        return (1 - result.anomaly_score, result.anomaly_score)

    def save(self, path: str | Path) -> None:
        if not self.is_trained:
            raise RuntimeError("Model not trained")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            "model": self.model,
            "scaler": self.scaler,
            "feature_names": self.feature_names,
            "threshold": self.threshold,
            "contamination": self.contamination,
            "n_estimators": self.n_estimators,
        }

        joblib.dump(model_data, path)
        logger.info("model_saved", path=str(path))

    @classmethod
    def load(cls, path: str | Path) -> IsolationForestDetector:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        model_data = joblib.load(path)

        detector = cls(
            contamination=model_data["contamination"],
            n_estimators=model_data["n_estimators"],
            threshold=model_data["threshold"],
        )

        detector.model = model_data["model"]
        detector.scaler = model_data["scaler"]
        detector.feature_names = model_data["feature_names"]
        detector.is_trained = True

        logger.info("model_loaded", path=str(path))
        return detector

    def update_threshold(self, new_threshold: float) -> None:
        if not 0 <= new_threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        self.threshold = new_threshold
        logger.info("threshold_updated", threshold=new_threshold)

    def evaluate(
        self,
        features: list[AggregatedFeatures] | np.ndarray,
        labels: list[int] | np.ndarray,
    ) -> dict[str, float]:
        if isinstance(features, np.ndarray):
            if len(features) != len(labels):
                raise ValueError("Features and labels must have same length")
            predictions = [self.predict_single(f).is_anomaly for f in features]
        else:
            if len(features) != len(labels):
                raise ValueError("Features and labels must have same length")
            predictions = [self.predict(f).is_anomaly for f in features]

        labels_list = labels.tolist() if isinstance(labels, np.ndarray) else labels

        tp = sum(1 for p, l in zip(predictions, labels_list) if p and l == 1)
        tn = sum(1 for p, l in zip(predictions, labels_list) if not p and l == 0)
        fp = sum(1 for p, l in zip(predictions, labels_list) if p and l == 0)
        fn = sum(1 for p, l in zip(predictions, labels_list) if not p and l == 1)

        accuracy = (tp + tn) / len(labels_list) if len(labels_list) > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "true_positives": tp,
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def _normalize_score(self, raw_score: float) -> float:
        normalized = 0.5 - raw_score / 2
        return max(0.0, min(1.0, normalized))

    def _calculate_confidence(self, anomaly_score: float) -> float:
        distance_from_threshold = abs(anomaly_score - self.threshold)
        return min(0.5 + distance_from_threshold, 1.0)

    def _calculate_feature_importances(self, X: np.ndarray) -> dict[str, float]:
        if self.model is None:
            return {}

        n_features = X.shape[1]
        importances = np.zeros(n_features)

        for tree in self.model.estimators_:
            feature_indices = tree.tree_.feature
            for idx in feature_indices:
                if idx >= 0:
                    importances[idx] += 1

        importances = importances / importances.sum() if importances.sum() > 0 else importances

        return {
            name: float(imp)
            for name, imp in zip(self.feature_names, importances)
        }

    def _calculate_feature_contributions(self, x: np.ndarray) -> dict[str, float]:
        if self.model is None or self.scaler is None:
            return {}

        contributions: dict[str, float] = {}
        mean = self.scaler.mean_
        std = self.scaler.scale_

        for i, (name, val, m, s) in enumerate(zip(self.feature_names, x, mean, std)):
            z_score = abs(val)
            contributions[name] = float(z_score)

        total = sum(contributions.values())
        if total > 0:
            contributions = {k: v / total for k, v in contributions.items()}

        return dict(sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:10])


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Train Isolation Forest model")
    parser.add_argument("--train", action="store_true", help="Train the model")
    parser.add_argument("--data", type=str, default="data/traces", help="Path to training data")
    parser.add_argument("--output", type=str, default="models/isolation_forest.joblib", help="Output model path")
    parser.add_argument("--contamination", type=float, default=0.1, help="Contamination ratio")
    parser.add_argument("--threshold", type=float, default=0.65, help="Detection threshold")

    args = parser.parse_args()

    if args.train:
        logger.info("Training mode not implemented in CLI yet")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

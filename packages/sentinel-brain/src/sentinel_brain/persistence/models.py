"""
Data models for persistence layer.

Defines the schema for storing analysis records, alerts, and metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AlertStatus(Enum):
    """Status of an alert."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    RESOLVED = "resolved"


@dataclass
class Alert:
    """
    Alert record for suspicious transactions.

    Stores high-risk detections for review and tracking.
    """

    id: str
    tx_hash: str
    created_at: datetime
    risk_level: str
    risk_score: float
    confidence: float
    risk_indicators: list[str]
    protocol: str
    operation: str
    explanation: str
    status: AlertStatus = AlertStatus.PENDING
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tx_hash": self.tx_hash,
            "created_at": self.created_at.isoformat(),
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "risk_indicators": self.risk_indicators,
            "protocol": self.protocol,
            "operation": self.operation,
            "explanation": self.explanation,
            "status": self.status.value,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewed_by": self.reviewed_by,
            "notes": self.notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            tx_hash=data["tx_hash"],
            created_at=datetime.fromisoformat(data["created_at"]),
            risk_level=data["risk_level"],
            risk_score=data["risk_score"],
            confidence=data["confidence"],
            risk_indicators=data["risk_indicators"],
            protocol=data["protocol"],
            operation=data["operation"],
            explanation=data["explanation"],
            status=AlertStatus(data["status"]),
            reviewed_at=datetime.fromisoformat(data["reviewed_at"]) if data.get("reviewed_at") else None,
            reviewed_by=data.get("reviewed_by"),
            notes=data.get("notes"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AnalysisRecord:
    """
    Record of a transaction analysis.

    Stores all analyzed transactions for audit and training purposes.
    """

    id: str
    tx_hash: str
    analyzed_at: datetime
    risk_level: str
    risk_score: float
    raw_risk_score: float
    confidence: float
    heuristic_result: str
    ml_score: float
    risk_indicators: list[str]
    protocol: str
    operation: str
    risk_adjustment: float
    latency_ms: float
    from_address: str
    to_address: str | None
    value_wei: str
    gas: int
    input_data_hash: str
    features: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tx_hash": self.tx_hash,
            "analyzed_at": self.analyzed_at.isoformat(),
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "raw_risk_score": self.raw_risk_score,
            "confidence": self.confidence,
            "heuristic_result": self.heuristic_result,
            "ml_score": self.ml_score,
            "risk_indicators": self.risk_indicators,
            "protocol": self.protocol,
            "operation": self.operation,
            "risk_adjustment": self.risk_adjustment,
            "latency_ms": self.latency_ms,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "value_wei": self.value_wei,
            "gas": self.gas,
            "input_data_hash": self.input_data_hash,
            "features": self.features,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisRecord:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            tx_hash=data["tx_hash"],
            analyzed_at=datetime.fromisoformat(data["analyzed_at"]),
            risk_level=data["risk_level"],
            risk_score=data["risk_score"],
            raw_risk_score=data["raw_risk_score"],
            confidence=data["confidence"],
            heuristic_result=data["heuristic_result"],
            ml_score=data["ml_score"],
            risk_indicators=data["risk_indicators"],
            protocol=data["protocol"],
            operation=data["operation"],
            risk_adjustment=data["risk_adjustment"],
            latency_ms=data["latency_ms"],
            from_address=data["from_address"],
            to_address=data.get("to_address"),
            value_wei=data["value_wei"],
            gas=data["gas"],
            input_data_hash=data["input_data_hash"],
            features=data.get("features", {}),
        )


@dataclass
class ModelMetrics:
    """
    Model performance metrics snapshot.

    Tracks accuracy, precision, recall, and other metrics over time.
    """

    id: str
    recorded_at: datetime
    model_version: str
    total_analyzed: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    average_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    by_risk_level: dict[str, int] = field(default_factory=dict)
    by_protocol: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "recorded_at": self.recorded_at.isoformat(),
            "model_version": self.model_version,
            "total_analyzed": self.total_analyzed,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "average_latency_ms": self.average_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "by_risk_level": self.by_risk_level,
            "by_protocol": self.by_protocol,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelMetrics:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
            model_version=data["model_version"],
            total_analyzed=data["total_analyzed"],
            true_positives=data["true_positives"],
            false_positives=data["false_positives"],
            true_negatives=data["true_negatives"],
            false_negatives=data["false_negatives"],
            accuracy=data["accuracy"],
            precision=data["precision"],
            recall=data["recall"],
            f1_score=data["f1_score"],
            average_latency_ms=data["average_latency_ms"],
            p95_latency_ms=data["p95_latency_ms"],
            p99_latency_ms=data["p99_latency_ms"],
            by_risk_level=data.get("by_risk_level", {}),
            by_protocol=data.get("by_protocol", {}),
        )

"""
Database layer for Sentinel Brain.

Supports both SQLite (development) and PostgreSQL (production).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterator

import structlog

from sentinel_brain.persistence.models import Alert, AlertStatus, AnalysisRecord, ModelMetrics

logger = structlog.get_logger()


@dataclass
class DatabaseConfig:
    """Database configuration."""

    # SQLite settings
    sqlite_path: str = "data/sentinel.db"

    # PostgreSQL settings (for production)
    postgres_url: str | None = None

    # General settings
    pool_size: int = 5
    max_overflow: int = 10

    @property
    def is_postgres(self) -> bool:
        """Check if using PostgreSQL."""
        return self.postgres_url is not None


class DatabaseBackend(ABC):
    """Abstract database backend."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema."""
        pass

    @abstractmethod
    def save_alert(self, alert: Alert) -> None:
        """Save an alert."""
        pass

    @abstractmethod
    def get_alert(self, alert_id: str) -> Alert | None:
        """Get alert by ID."""
        pass

    @abstractmethod
    def get_alerts(
        self,
        status: AlertStatus | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Alert]:
        """Get alerts with filters."""
        pass

    @abstractmethod
    def update_alert_status(
        self,
        alert_id: str,
        status: AlertStatus,
        reviewed_by: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update alert status."""
        pass

    @abstractmethod
    def save_analysis(self, record: AnalysisRecord) -> None:
        """Save analysis record."""
        pass

    @abstractmethod
    def get_analysis(self, record_id: str) -> AnalysisRecord | None:
        """Get analysis record by ID."""
        pass

    @abstractmethod
    def get_analysis_by_tx(self, tx_hash: str) -> AnalysisRecord | None:
        """Get analysis record by transaction hash."""
        pass

    @abstractmethod
    def get_recent_analyses(
        self,
        limit: int = 100,
        risk_level: str | None = None,
    ) -> list[AnalysisRecord]:
        """Get recent analysis records."""
        pass

    @abstractmethod
    def save_metrics(self, metrics: ModelMetrics) -> None:
        """Save model metrics snapshot."""
        pass

    @abstractmethod
    def get_latest_metrics(self) -> ModelMetrics | None:
        """Get latest metrics snapshot."""
        pass

    @abstractmethod
    def get_metrics_history(
        self,
        days: int = 30,
    ) -> list[ModelMetrics]:
        """Get metrics history."""
        pass


class SQLiteBackend(DatabaseBackend):
    """SQLite database backend."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    tx_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    risk_indicators TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    notes TEXT,
                    metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_tx_hash ON alerts(tx_hash);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
                CREATE INDEX IF NOT EXISTS idx_alerts_risk_level ON alerts(risk_level);
                CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);

                CREATE TABLE IF NOT EXISTS analysis_records (
                    id TEXT PRIMARY KEY,
                    tx_hash TEXT NOT NULL UNIQUE,
                    analyzed_at TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    raw_risk_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    heuristic_result TEXT NOT NULL,
                    ml_score REAL NOT NULL,
                    risk_indicators TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    risk_adjustment REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    from_address TEXT NOT NULL,
                    to_address TEXT,
                    value_wei TEXT NOT NULL,
                    gas INTEGER NOT NULL,
                    input_data_hash TEXT NOT NULL,
                    features TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_tx_hash ON analysis_records(tx_hash);
                CREATE INDEX IF NOT EXISTS idx_analysis_risk_level ON analysis_records(risk_level);
                CREATE INDEX IF NOT EXISTS idx_analysis_analyzed_at ON analysis_records(analyzed_at);

                CREATE TABLE IF NOT EXISTS model_metrics (
                    id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    total_analyzed INTEGER NOT NULL,
                    true_positives INTEGER NOT NULL,
                    false_positives INTEGER NOT NULL,
                    true_negatives INTEGER NOT NULL,
                    false_negatives INTEGER NOT NULL,
                    accuracy REAL NOT NULL,
                    precision_score REAL NOT NULL,
                    recall REAL NOT NULL,
                    f1_score REAL NOT NULL,
                    average_latency_ms REAL NOT NULL,
                    p95_latency_ms REAL NOT NULL,
                    p99_latency_ms REAL NOT NULL,
                    by_risk_level TEXT,
                    by_protocol TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_metrics_recorded_at ON model_metrics(recorded_at);
            """)
            conn.commit()
            logger.info("database_initialized", path=str(self.db_path))

    def save_alert(self, alert: Alert) -> None:
        """Save an alert."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts (
                    id, tx_hash, created_at, risk_level, risk_score, confidence,
                    risk_indicators, protocol, operation, explanation, status,
                    reviewed_at, reviewed_by, notes, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.id,
                    alert.tx_hash,
                    alert.created_at.isoformat(),
                    alert.risk_level,
                    alert.risk_score,
                    alert.confidence,
                    json.dumps(alert.risk_indicators),
                    alert.protocol,
                    alert.operation,
                    alert.explanation,
                    alert.status.value,
                    alert.reviewed_at.isoformat() if alert.reviewed_at else None,
                    alert.reviewed_by,
                    alert.notes,
                    json.dumps(alert.metadata),
                ),
            )
            conn.commit()

    def get_alert(self, alert_id: str) -> Alert | None:
        """Get alert by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            if row:
                return self._row_to_alert(row)
            return None

    def get_alerts(
        self,
        status: AlertStatus | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Alert]:
        """Get alerts with filters."""
        query = "SELECT * FROM alerts WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if risk_level:
            query += " AND risk_level = ?"
            params.append(risk_level)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_alert(row) for row in rows]

    def update_alert_status(
        self,
        alert_id: str,
        status: AlertStatus,
        reviewed_by: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update alert status."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts SET
                    status = ?,
                    reviewed_at = ?,
                    reviewed_by = ?,
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (
                    status.value,
                    datetime.now(timezone.utc).isoformat(),
                    reviewed_by,
                    notes,
                    alert_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def save_analysis(self, record: AnalysisRecord) -> None:
        """Save analysis record."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_records (
                    id, tx_hash, analyzed_at, risk_level, risk_score, raw_risk_score,
                    confidence, heuristic_result, ml_score, risk_indicators, protocol,
                    operation, risk_adjustment, latency_ms, from_address, to_address,
                    value_wei, gas, input_data_hash, features
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tx_hash,
                    record.analyzed_at.isoformat(),
                    record.risk_level,
                    record.risk_score,
                    record.raw_risk_score,
                    record.confidence,
                    record.heuristic_result,
                    record.ml_score,
                    json.dumps(record.risk_indicators),
                    record.protocol,
                    record.operation,
                    record.risk_adjustment,
                    record.latency_ms,
                    record.from_address,
                    record.to_address,
                    record.value_wei,
                    record.gas,
                    record.input_data_hash,
                    json.dumps(record.features),
                ),
            )
            conn.commit()

    def get_analysis(self, record_id: str) -> AnalysisRecord | None:
        """Get analysis record by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_records WHERE id = ?", (record_id,)
            ).fetchone()
            if row:
                return self._row_to_analysis(row)
            return None

    def get_analysis_by_tx(self, tx_hash: str) -> AnalysisRecord | None:
        """Get analysis record by transaction hash."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_records WHERE tx_hash = ?", (tx_hash,)
            ).fetchone()
            if row:
                return self._row_to_analysis(row)
            return None

    def get_recent_analyses(
        self,
        limit: int = 100,
        risk_level: str | None = None,
    ) -> list[AnalysisRecord]:
        """Get recent analysis records."""
        query = "SELECT * FROM analysis_records"
        params: list[Any] = []

        if risk_level:
            query += " WHERE risk_level = ?"
            params.append(risk_level)

        query += " ORDER BY analyzed_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_analysis(row) for row in rows]

    def save_metrics(self, metrics: ModelMetrics) -> None:
        """Save model metrics snapshot."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO model_metrics (
                    id, recorded_at, model_version, total_analyzed, true_positives,
                    false_positives, true_negatives, false_negatives, accuracy,
                    precision_score, recall, f1_score, average_latency_ms,
                    p95_latency_ms, p99_latency_ms, by_risk_level, by_protocol
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.id,
                    metrics.recorded_at.isoformat(),
                    metrics.model_version,
                    metrics.total_analyzed,
                    metrics.true_positives,
                    metrics.false_positives,
                    metrics.true_negatives,
                    metrics.false_negatives,
                    metrics.accuracy,
                    metrics.precision,
                    metrics.recall,
                    metrics.f1_score,
                    metrics.average_latency_ms,
                    metrics.p95_latency_ms,
                    metrics.p99_latency_ms,
                    json.dumps(metrics.by_risk_level),
                    json.dumps(metrics.by_protocol),
                ),
            )
            conn.commit()

    def get_latest_metrics(self) -> ModelMetrics | None:
        """Get latest metrics snapshot."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_metrics ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
            if row:
                return self._row_to_metrics(row)
            return None

    def get_metrics_history(self, days: int = 30) -> list[ModelMetrics]:
        """Get metrics history."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM model_metrics
                WHERE recorded_at >= datetime('now', ?)
                ORDER BY recorded_at DESC
                """,
                (f"-{days} days",),
            ).fetchall()
            return [self._row_to_metrics(row) for row in rows]

    def _row_to_alert(self, row: sqlite3.Row) -> Alert:
        """Convert database row to Alert."""
        return Alert(
            id=row["id"],
            tx_hash=row["tx_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            risk_level=row["risk_level"],
            risk_score=row["risk_score"],
            confidence=row["confidence"],
            risk_indicators=json.loads(row["risk_indicators"]),
            protocol=row["protocol"],
            operation=row["operation"],
            explanation=row["explanation"],
            status=AlertStatus(row["status"]),
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None,
            reviewed_by=row["reviewed_by"],
            notes=row["notes"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _row_to_analysis(self, row: sqlite3.Row) -> AnalysisRecord:
        """Convert database row to AnalysisRecord."""
        return AnalysisRecord(
            id=row["id"],
            tx_hash=row["tx_hash"],
            analyzed_at=datetime.fromisoformat(row["analyzed_at"]),
            risk_level=row["risk_level"],
            risk_score=row["risk_score"],
            raw_risk_score=row["raw_risk_score"],
            confidence=row["confidence"],
            heuristic_result=row["heuristic_result"],
            ml_score=row["ml_score"],
            risk_indicators=json.loads(row["risk_indicators"]),
            protocol=row["protocol"],
            operation=row["operation"],
            risk_adjustment=row["risk_adjustment"],
            latency_ms=row["latency_ms"],
            from_address=row["from_address"],
            to_address=row["to_address"],
            value_wei=row["value_wei"],
            gas=row["gas"],
            input_data_hash=row["input_data_hash"],
            features=json.loads(row["features"]) if row["features"] else {},
        )

    def _row_to_metrics(self, row: sqlite3.Row) -> ModelMetrics:
        """Convert database row to ModelMetrics."""
        return ModelMetrics(
            id=row["id"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            model_version=row["model_version"],
            total_analyzed=row["total_analyzed"],
            true_positives=row["true_positives"],
            false_positives=row["false_positives"],
            true_negatives=row["true_negatives"],
            false_negatives=row["false_negatives"],
            accuracy=row["accuracy"],
            precision=row["precision_score"],
            recall=row["recall"],
            f1_score=row["f1_score"],
            average_latency_ms=row["average_latency_ms"],
            p95_latency_ms=row["p95_latency_ms"],
            p99_latency_ms=row["p99_latency_ms"],
            by_risk_level=json.loads(row["by_risk_level"]) if row["by_risk_level"] else {},
            by_protocol=json.loads(row["by_protocol"]) if row["by_protocol"] else {},
        )


class Database:
    """
    Main database interface.

    Automatically selects backend based on configuration.
    """

    def __init__(self, config: DatabaseConfig | None = None):
        self.config = config or DatabaseConfig()

        if self.config.is_postgres:
            # PostgreSQL backend would be implemented here
            raise NotImplementedError("PostgreSQL backend not yet implemented")
        else:
            self._backend = SQLiteBackend(self.config.sqlite_path)

    def initialize(self) -> None:
        """Initialize database."""
        self._backend.initialize()

    # Alert methods
    def save_alert(self, alert: Alert) -> None:
        """Save an alert."""
        self._backend.save_alert(alert)

    def get_alert(self, alert_id: str) -> Alert | None:
        """Get alert by ID."""
        return self._backend.get_alert(alert_id)

    def get_alerts(
        self,
        status: AlertStatus | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Alert]:
        """Get alerts with filters."""
        return self._backend.get_alerts(status, risk_level, limit, offset)

    def update_alert_status(
        self,
        alert_id: str,
        status: AlertStatus,
        reviewed_by: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update alert status."""
        return self._backend.update_alert_status(alert_id, status, reviewed_by, notes)

    # Analysis methods
    def save_analysis(self, record: AnalysisRecord) -> None:
        """Save analysis record."""
        self._backend.save_analysis(record)

    def get_analysis(self, record_id: str) -> AnalysisRecord | None:
        """Get analysis record by ID."""
        return self._backend.get_analysis(record_id)

    def get_analysis_by_tx(self, tx_hash: str) -> AnalysisRecord | None:
        """Get analysis record by transaction hash."""
        return self._backend.get_analysis_by_tx(tx_hash)

    def get_recent_analyses(
        self,
        limit: int = 100,
        risk_level: str | None = None,
    ) -> list[AnalysisRecord]:
        """Get recent analysis records."""
        return self._backend.get_recent_analyses(limit, risk_level)

    # Metrics methods
    def save_metrics(self, metrics: ModelMetrics) -> None:
        """Save model metrics snapshot."""
        self._backend.save_metrics(metrics)

    def get_latest_metrics(self) -> ModelMetrics | None:
        """Get latest metrics snapshot."""
        return self._backend.get_latest_metrics()

    def get_metrics_history(self, days: int = 30) -> list[ModelMetrics]:
        """Get metrics history."""
        return self._backend.get_metrics_history(days)

    # Utility methods
    @staticmethod
    def generate_id() -> str:
        """Generate a unique ID."""
        return str(uuid.uuid4())

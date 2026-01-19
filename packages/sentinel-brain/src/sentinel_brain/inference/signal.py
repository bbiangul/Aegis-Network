"""
Signal-only inference mode.

Instead of triggering pauses, this module provides risk signals that can be:
- Sent to monitoring dashboards
- Used for alerting (Slack, Discord, PagerDuty)
- Logged for analysis
- Fed to human operators for decision

This is the production-safe approach for MVP.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from pathlib import Path

import structlog

from sentinel_brain.data.collectors.fork_replayer import TransactionTrace
from sentinel_brain.features.aggregator import FeatureAggregator, AggregatedFeatures
from sentinel_brain.models.isolation_forest import IsolationForestDetector, DetectionResult
from sentinel_brain.models.heuristics import HeuristicFilter, HeuristicResult, FilterResult
from sentinel_brain.models.protocol_filter import ProtocolFilter, ProtocolContext


logger = structlog.get_logger()


class RiskLevel(Enum):
    """Risk levels for transaction signals."""
    SAFE = "safe"           # Normal transaction
    LOW = "low"             # Minor anomaly, log only
    MEDIUM = "medium"       # Needs attention, alert
    HIGH = "high"           # Likely attack, urgent alert
    CRITICAL = "critical"   # Almost certain attack, immediate escalation


@dataclass
class RiskSignal:
    """Risk signal for a transaction."""
    tx_hash: str
    timestamp: float
    risk_level: RiskLevel
    risk_score: float  # 0.0 - 1.0 (after protocol adjustment)
    confidence: float  # 0.0 - 1.0

    # Detailed breakdown
    ml_score: float
    ml_confidence: float
    heuristic_result: str
    heuristic_confidence: float
    risk_indicators: list[str]

    # Protocol context
    protocol: str
    operation: str
    raw_risk_score: float  # Before protocol adjustment
    risk_adjustment: float

    # Feature summary
    has_flash_loan: bool
    flash_loan_amount: float
    unique_contracts: int
    transfer_count: int
    max_value_delta: float
    call_depth: int

    # Recommendations
    recommended_action: str
    explanation: str

    # Metadata
    latency_ms: float
    model_version: str = "v2.1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "timestamp": self.timestamp,
            "risk_level": self.risk_level.value,
            "risk_score": round(self.risk_score, 4),
            "raw_risk_score": round(self.raw_risk_score, 4),
            "confidence": round(self.confidence, 4),
            "ml": {
                "score": round(self.ml_score, 4),
                "confidence": round(self.ml_confidence, 4),
            },
            "heuristic": {
                "result": self.heuristic_result,
                "confidence": round(self.heuristic_confidence, 4),
            },
            "protocol": {
                "name": self.protocol,
                "operation": self.operation,
                "risk_adjustment": round(self.risk_adjustment, 4),
            },
            "risk_indicators": self.risk_indicators,
            "features": {
                "has_flash_loan": self.has_flash_loan,
                "flash_loan_amount_eth": round(self.flash_loan_amount, 2),
                "unique_contracts": self.unique_contracts,
                "transfer_count": self.transfer_count,
                "max_value_delta_eth": round(self.max_value_delta, 2),
                "call_depth": self.call_depth,
            },
            "recommended_action": self.recommended_action,
            "explanation": self.explanation,
            "latency_ms": round(self.latency_ms, 2),
            "model_version": self.model_version,
        }

    def to_alert_message(self) -> str:
        """Format as human-readable alert message."""
        emoji = {
            RiskLevel.SAFE: "✅",
            RiskLevel.LOW: "📝",
            RiskLevel.MEDIUM: "⚠️",
            RiskLevel.HIGH: "🚨",
            RiskLevel.CRITICAL: "🔴",
        }[self.risk_level]

        msg = f"""
{emoji} **{self.risk_level.value.upper()} RISK DETECTED**

**Transaction:** `{self.tx_hash[:18]}...`
**Risk Score:** {self.risk_score:.2%}
**Confidence:** {self.confidence:.2%}

**Risk Indicators:**
{chr(10).join(f"  • {ind}" for ind in self.risk_indicators[:5])}

**Key Features:**
  • Flash Loan: {"Yes (" + f"{self.flash_loan_amount:,.0f} ETH)" if self.has_flash_loan else "No"}
  • Contracts Involved: {self.unique_contracts}
  • Transfers: {self.transfer_count}
  • Max Value Movement: {self.max_value_delta:,.2f} ETH

**Recommendation:** {self.recommended_action}

**Explanation:** {self.explanation}
        """.strip()
        return msg


# Type for alert callbacks
AlertCallback = Callable[[RiskSignal], None]


class SignalEngine:
    """
    Signal-only inference engine.

    Analyzes transactions and emits risk signals without taking action.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        alert_callbacks: list[AlertCallback] | None = None,
        min_alert_level: RiskLevel = RiskLevel.MEDIUM,
        enable_protocol_filter: bool = True,
    ):
        self.feature_aggregator = FeatureAggregator()
        self.heuristic_filter = HeuristicFilter()
        self.protocol_filter = ProtocolFilter() if enable_protocol_filter else None
        self.alert_callbacks = alert_callbacks or []
        self.min_alert_level = min_alert_level
        self.enable_protocol_filter = enable_protocol_filter

        self.ml_detector: IsolationForestDetector | None = None
        if model_path:
            self.ml_detector = IsolationForestDetector.load(model_path)

        # Statistics
        self._stats = {
            "total_analyzed": 0,
            "safe": 0,
            "low": 0,
            "medium": 0,
            "high": 0,
            "critical": 0,
            "total_latency_ms": 0.0,
            "protocol_adjustments": 0,
        }

    def analyze(self, trace: TransactionTrace) -> RiskSignal:
        """Analyze a transaction and return risk signal."""
        start_time = time.perf_counter()

        # Extract features
        import asyncio
        features = asyncio.get_event_loop().run_until_complete(
            self.feature_aggregator.extract_from_trace(trace)
        )

        # Run heuristics
        heuristic = self.heuristic_filter.filter_with_features(features)

        # Run ML if available
        ml_result: DetectionResult | None = None
        if self.ml_detector:
            ml_result = self.ml_detector.predict(features)

        # Compute risk level and score
        risk_level, risk_score, confidence = self._compute_risk(heuristic, ml_result)

        # Generate explanation
        explanation = self._generate_explanation(features, heuristic, ml_result, risk_level)

        # Build signal
        latency = (time.perf_counter() - start_time) * 1000

        signal = RiskSignal(
            tx_hash=trace.tx_hash,
            timestamp=time.time(),
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            ml_score=ml_result.anomaly_score if ml_result else 0.0,
            ml_confidence=ml_result.confidence if ml_result else 0.0,
            heuristic_result=heuristic.result.value,
            heuristic_confidence=heuristic.confidence,
            risk_indicators=heuristic.risk_indicators,
            has_flash_loan=features.flash_loan.has_flash_loan,
            flash_loan_amount=features.flash_loan.total_borrowed / 1e18,
            unique_contracts=features.state_variance.unique_contracts_modified,
            transfer_count=features.state_variance.total_storage_changes,
            max_value_delta=features.state_variance.max_value_delta / 1e18,
            call_depth=features.opcode.call_depth,
            recommended_action=self._get_recommendation(risk_level),
            explanation=explanation,
            latency_ms=latency,
        )

        # Update stats
        self._stats["total_analyzed"] += 1
        self._stats[risk_level.value] += 1
        self._stats["total_latency_ms"] += latency

        # Emit alerts
        self._emit_alerts(signal)

        logger.info(
            "signal_generated",
            tx_hash=trace.tx_hash[:18],
            risk_level=risk_level.value,
            risk_score=round(risk_score, 4),
            latency_ms=round(latency, 2),
        )

        return signal

    async def analyze_async(self, trace: TransactionTrace) -> RiskSignal:
        """Async version of analyze."""
        start_time = time.perf_counter()

        # Extract features
        features = await self.feature_aggregator.extract_from_trace(trace)

        # Run heuristics
        heuristic = self.heuristic_filter.filter_with_features(features)

        # Run ML if available
        ml_result: DetectionResult | None = None
        if self.ml_detector:
            ml_result = self.ml_detector.predict(features)

        # Compute raw risk level and score
        risk_level, raw_risk_score, confidence = self._compute_risk(heuristic, ml_result)

        # Apply protocol filter
        protocol_name = "unknown"
        operation_name = "unknown"
        risk_adjustment = 0.0
        risk_score = raw_risk_score

        if self.protocol_filter:
            filter_result = self.protocol_filter.filter(
                features,
                raw_risk_score,
                trace.to_address,
                trace.input_data,
            )
            risk_score = filter_result.adjusted_risk_score
            protocol_name = filter_result.context.protocol.value
            operation_name = filter_result.context.operation.value
            risk_adjustment = filter_result.context.risk_adjustment

            if risk_adjustment != 0:
                self._stats["protocol_adjustments"] += 1

            # Recompute risk level with adjusted score
            risk_level = self._score_to_level(risk_score, heuristic, ml_result)

        # Generate explanation
        explanation = self._generate_explanation(features, heuristic, ml_result, risk_level)
        if protocol_name != "unknown":
            explanation = f"Protocol: {protocol_name} ({operation_name}). " + explanation

        # Build signal
        latency = (time.perf_counter() - start_time) * 1000

        signal = RiskSignal(
            tx_hash=trace.tx_hash,
            timestamp=time.time(),
            risk_level=risk_level,
            risk_score=risk_score,
            confidence=confidence,
            ml_score=ml_result.anomaly_score if ml_result else 0.0,
            ml_confidence=ml_result.confidence if ml_result else 0.0,
            heuristic_result=heuristic.result.value,
            heuristic_confidence=heuristic.confidence,
            risk_indicators=heuristic.risk_indicators,
            protocol=protocol_name,
            operation=operation_name,
            raw_risk_score=raw_risk_score,
            risk_adjustment=risk_adjustment,
            has_flash_loan=features.flash_loan.has_flash_loan,
            flash_loan_amount=features.flash_loan.total_borrowed / 1e18,
            unique_contracts=features.state_variance.unique_contracts_modified,
            transfer_count=features.state_variance.total_storage_changes,
            max_value_delta=features.state_variance.max_value_delta / 1e18,
            call_depth=features.opcode.call_depth,
            recommended_action=self._get_recommendation(risk_level),
            explanation=explanation,
            latency_ms=latency,
        )

        # Update stats
        self._stats["total_analyzed"] += 1
        self._stats[risk_level.value] += 1
        self._stats["total_latency_ms"] += latency

        # Emit alerts
        self._emit_alerts(signal)

        return signal

    def _score_to_level(
        self,
        risk_score: float,
        heuristic: HeuristicResult,
        ml_result: DetectionResult | None,
    ) -> RiskLevel:
        """Convert adjusted risk score to risk level."""
        if risk_score >= 0.7:
            return RiskLevel.CRITICAL
        elif risk_score >= 0.5:
            return RiskLevel.HIGH
        elif risk_score >= 0.35:
            return RiskLevel.MEDIUM
        elif risk_score >= 0.2:
            return RiskLevel.LOW
        else:
            return RiskLevel.SAFE

    def _compute_risk(
        self,
        heuristic: HeuristicResult,
        ml_result: DetectionResult | None,
    ) -> tuple[RiskLevel, float, float]:
        """Compute overall risk level, score, and confidence."""

        # Base scores
        heuristic_score = len(heuristic.risk_indicators) / 10  # Normalize to 0-1
        ml_score = ml_result.anomaly_score if ml_result else 0.0

        # Combined score (weighted average)
        if ml_result:
            risk_score = 0.4 * heuristic_score + 0.6 * ml_score
            confidence = 0.4 * heuristic.confidence + 0.6 * ml_result.confidence
        else:
            risk_score = heuristic_score
            confidence = heuristic.confidence

        # Determine risk level based on combined signals
        if heuristic.result == FilterResult.SUSPICIOUS and heuristic.confidence > 0.9:
            risk_level = RiskLevel.CRITICAL
        elif heuristic.result == FilterResult.SUSPICIOUS and ml_result and ml_result.is_anomaly:
            risk_level = RiskLevel.HIGH
        elif heuristic.result == FilterResult.SUSPICIOUS:
            risk_level = RiskLevel.MEDIUM
        elif ml_result and ml_result.is_anomaly:
            risk_level = RiskLevel.MEDIUM if ml_result.confidence > 0.7 else RiskLevel.LOW
        elif len(heuristic.risk_indicators) >= 2:
            risk_level = RiskLevel.LOW
        else:
            risk_level = RiskLevel.SAFE

        return risk_level, min(risk_score, 1.0), min(confidence, 1.0)

    def _get_recommendation(self, risk_level: RiskLevel) -> str:
        """Get recommended action based on risk level."""
        recommendations = {
            RiskLevel.SAFE: "No action required",
            RiskLevel.LOW: "Log and monitor",
            RiskLevel.MEDIUM: "Alert security team for review",
            RiskLevel.HIGH: "Immediate review required - consider manual pause",
            RiskLevel.CRITICAL: "URGENT: Likely attack in progress - activate incident response",
        }
        return recommendations[risk_level]

    def _generate_explanation(
        self,
        features: AggregatedFeatures,
        heuristic: HeuristicResult,
        ml_result: DetectionResult | None,
        risk_level: RiskLevel,
    ) -> str:
        """Generate human-readable explanation of the risk assessment."""
        explanations = []

        if features.flash_loan.has_flash_loan:
            amount = features.flash_loan.total_borrowed / 1e18
            providers = ", ".join(features.flash_loan.flash_loan_providers) or "unknown"
            explanations.append(f"Flash loan detected ({amount:,.0f} ETH from {providers})")

        if features.state_variance.large_value_changes > 3:
            explanations.append(
                f"Multiple large value movements ({features.state_variance.large_value_changes} changes)"
            )

        if features.state_variance.max_value_delta > 1e22:  # > 10k ETH
            delta = features.state_variance.max_value_delta / 1e18
            explanations.append(f"Extreme value movement detected ({delta:,.0f} ETH)")

        if features.opcode.call_depth > 5:
            explanations.append(f"Deep call stack ({features.opcode.call_depth} levels)")

        if features.state_variance.variance_ratio > 0.5:
            explanations.append("High state variance detected")

        if ml_result and ml_result.is_anomaly:
            explanations.append(f"ML model flagged as anomaly (score: {ml_result.anomaly_score:.2f})")

        if not explanations:
            if risk_level == RiskLevel.SAFE:
                return "Transaction appears normal with no suspicious patterns"
            return "Minor anomalies detected but within normal parameters"

        return ". ".join(explanations) + "."

    def _emit_alerts(self, signal: RiskSignal) -> None:
        """Emit alerts to registered callbacks."""
        risk_priority = {
            RiskLevel.SAFE: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }

        if risk_priority[signal.risk_level] >= risk_priority[self.min_alert_level]:
            for callback in self.alert_callbacks:
                try:
                    callback(signal)
                except Exception as e:
                    logger.error("alert_callback_failed", error=str(e))

    def add_alert_callback(self, callback: AlertCallback) -> None:
        """Add an alert callback."""
        self.alert_callbacks.append(callback)

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics."""
        total = self._stats["total_analyzed"]
        return {
            "total_analyzed": total,
            "by_risk_level": {
                "safe": self._stats["safe"],
                "low": self._stats["low"],
                "medium": self._stats["medium"],
                "high": self._stats["high"],
                "critical": self._stats["critical"],
            },
            "avg_latency_ms": (
                self._stats["total_latency_ms"] / total if total > 0 else 0.0
            ),
            "alert_rate": (
                (self._stats["medium"] + self._stats["high"] + self._stats["critical"]) / total
                if total > 0 else 0.0
            ),
        }

    @classmethod
    def load(cls, model_path: str | Path) -> SignalEngine:
        """Load a signal engine with a trained model."""
        return cls(model_path=model_path)


# Example alert callbacks
def console_alert(signal: RiskSignal) -> None:
    """Print alert to console."""
    print(signal.to_alert_message())


def json_alert(signal: RiskSignal) -> None:
    """Print alert as JSON."""
    import json
    print(json.dumps(signal.to_dict(), indent=2))


def webhook_alert_factory(webhook_url: str) -> AlertCallback:
    """Create a webhook alert callback."""
    import urllib.request
    import json

    def webhook_alert(signal: RiskSignal) -> None:
        data = json.dumps(signal.to_dict()).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.error("webhook_alert_failed", url=webhook_url, error=str(e))

    return webhook_alert

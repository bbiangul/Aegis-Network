from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from web3 import AsyncWeb3, AsyncHTTPProvider

from sentinel_brain.data.collectors.fork_replayer import ForkReplayer, TransactionTrace
from sentinel_brain.data.collectors.mempool_listener import PendingTransaction
from sentinel_brain.features.aggregator import FeatureAggregator, AggregatedFeatures
from sentinel_brain.models.heuristics import HeuristicFilter, HeuristicResult, FilterResult
from sentinel_brain.models.isolation_forest import IsolationForestDetector, DetectionResult


logger = structlog.get_logger()


@dataclass
class InferenceResult:
    tx_hash: str
    is_suspicious: bool
    anomaly_score: float
    confidence: float
    heuristic_result: HeuristicResult
    ml_result: DetectionResult | None
    features: AggregatedFeatures | None
    latency_ms: float
    risk_level: str
    risk_indicators: list[str]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "is_suspicious": self.is_suspicious,
            "anomaly_score": self.anomaly_score,
            "confidence": self.confidence,
            "heuristic": self.heuristic_result.to_dict(),
            "ml_result": self.ml_result.to_dict() if self.ml_result else None,
            "features": self.features.to_dict() if self.features else None,
            "latency_ms": self.latency_ms,
            "risk_level": self.risk_level,
            "risk_indicators": self.risk_indicators,
            "recommendation": self.recommendation,
        }


@dataclass
class EngineStats:
    total_analyzed: int
    safe_filtered: int
    suspicious_detected: int
    ml_analyzed: int
    avg_latency_ms: float
    false_positive_estimate: float


class InferenceEngine:
    def __init__(
        self,
        rpc_url: str,
        model_path: str | Path | None = None,
        heuristic_filter: HeuristicFilter | None = None,
        feature_aggregator: FeatureAggregator | None = None,
        enable_simulation: bool = True,
        simulation_timeout_ms: int = 200,
        anomaly_threshold: float = 0.65,
    ):
        self.rpc_url = rpc_url
        self.enable_simulation = enable_simulation
        self.simulation_timeout_ms = simulation_timeout_ms
        self.anomaly_threshold = anomaly_threshold

        self.heuristic_filter = heuristic_filter or HeuristicFilter()
        self.feature_aggregator = feature_aggregator or FeatureAggregator()

        self.ml_detector: IsolationForestDetector | None = None
        if model_path:
            self.ml_detector = IsolationForestDetector.load(model_path)

        self.fork_replayer: ForkReplayer | None = None
        if enable_simulation:
            self.fork_replayer = ForkReplayer(rpc_url)

        self.w3: AsyncWeb3 | None = None

        self._stats = {
            "total_analyzed": 0,
            "safe_filtered": 0,
            "suspicious_detected": 0,
            "ml_analyzed": 0,
            "total_latency_ms": 0.0,
        }

    async def initialize(self) -> None:
        self.w3 = AsyncWeb3(AsyncHTTPProvider(self.rpc_url))
        if not await self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to {self.rpc_url}")
        logger.info("inference_engine_initialized", rpc=self.rpc_url)

    async def analyze(self, tx: PendingTransaction) -> InferenceResult:
        start_time = time.perf_counter()
        self._stats["total_analyzed"] += 1

        heuristic_result = self.heuristic_filter.filter(tx)

        if heuristic_result.result == FilterResult.SAFE and not heuristic_result.should_analyze:
            self._stats["safe_filtered"] += 1
            latency = (time.perf_counter() - start_time) * 1000

            return InferenceResult(
                tx_hash=tx.hash,
                is_suspicious=False,
                anomaly_score=0.0,
                confidence=heuristic_result.confidence,
                heuristic_result=heuristic_result,
                ml_result=None,
                features=None,
                latency_ms=latency,
                risk_level="low",
                risk_indicators=[],
                recommendation="allow",
            )

        features = self.feature_aggregator.extract_from_pending(tx)

        # FIX: Track simulation status for risk assessment
        simulation_timeout = False
        simulation_error = False

        if self.enable_simulation and self.fork_replayer:
            try:
                trace = await asyncio.wait_for(
                    self._simulate_transaction(tx),
                    timeout=self.simulation_timeout_ms / 1000,
                )
                if trace:
                    features = await self.feature_aggregator.extract_from_trace(trace)
            except asyncio.TimeoutError:
                # FIX: Simulation timeout can indicate complex/suspicious transaction
                simulation_timeout = True
                logger.debug("simulation_timeout", tx_hash=tx.hash, timeout_ms=self.simulation_timeout_ms)
            except Exception as e:
                # FIX: Track simulation errors - may indicate unusual transaction
                simulation_error = True
                logger.debug("simulation_error", tx_hash=tx.hash, error=str(e))

        heuristic_with_features = self.heuristic_filter.filter_with_features(features)

        ml_result: DetectionResult | None = None
        if self.ml_detector:
            self._stats["ml_analyzed"] += 1
            ml_result = self.ml_detector.predict(features)

        # FIX: Pass simulation timeout to decision making - can indicate complex/suspicious tx
        is_suspicious, risk_level, recommendation = self._make_decision(
            heuristic_with_features, ml_result, simulation_timeout
        )

        if is_suspicious:
            self._stats["suspicious_detected"] += 1

        latency = (time.perf_counter() - start_time) * 1000
        self._stats["total_latency_ms"] += latency

        # FIX: Collect all risk indicators including simulation status
        all_indicators = list(set(
            heuristic_result.risk_indicators +
            heuristic_with_features.risk_indicators
        ))

        # FIX: Add simulation timeout/error as risk indicators
        if simulation_timeout:
            all_indicators.append("simulation_timeout")
        if simulation_error:
            all_indicators.append("simulation_error")

        return InferenceResult(
            tx_hash=tx.hash,
            is_suspicious=is_suspicious,
            anomaly_score=ml_result.anomaly_score if ml_result else 0.0,
            confidence=self._calculate_overall_confidence(heuristic_with_features, ml_result),
            heuristic_result=heuristic_with_features,
            ml_result=ml_result,
            features=features,
            latency_ms=latency,
            risk_level=risk_level,
            risk_indicators=all_indicators,
            recommendation=recommendation,
        )

    async def analyze_trace(self, trace: TransactionTrace) -> InferenceResult:
        start_time = time.perf_counter()

        features = await self.feature_aggregator.extract_from_trace(trace)
        heuristic_result = self.heuristic_filter.filter_with_features(features)

        ml_result: DetectionResult | None = None
        if self.ml_detector:
            ml_result = self.ml_detector.predict(features)

        is_suspicious, risk_level, recommendation = self._make_decision(
            heuristic_result, ml_result
        )

        latency = (time.perf_counter() - start_time) * 1000

        return InferenceResult(
            tx_hash=trace.tx_hash,
            is_suspicious=is_suspicious,
            anomaly_score=ml_result.anomaly_score if ml_result else 0.0,
            confidence=self._calculate_overall_confidence(heuristic_result, ml_result),
            heuristic_result=heuristic_result,
            ml_result=ml_result,
            features=features,
            latency_ms=latency,
            risk_level=risk_level,
            risk_indicators=heuristic_result.risk_indicators,
            recommendation=recommendation,
        )

    async def analyze_batch(
        self,
        transactions: list[PendingTransaction],
        max_concurrent: int = 10,
    ) -> list[InferenceResult]:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def analyze_with_semaphore(tx: PendingTransaction) -> InferenceResult:
            async with semaphore:
                return await self.analyze(tx)

        results = await asyncio.gather(
            *[analyze_with_semaphore(tx) for tx in transactions]
        )

        return list(results)

    def quick_filter(self, tx: PendingTransaction) -> bool:
        return self.heuristic_filter.quick_filter(tx)

    async def _simulate_transaction(self, tx: PendingTransaction) -> TransactionTrace | None:
        if not self.fork_replayer or not self.w3:
            return None

        try:
            current_block = await self.w3.eth.block_number
            trace = await self.fork_replayer.replay_transaction(
                tx.hash,
                fork_block=current_block - 1,
            )
            return trace
        except Exception as e:
            logger.debug("simulation_failed", tx_hash=tx.hash, error=str(e))
            return None

    def _make_decision(
        self,
        heuristic: HeuristicResult,
        ml_result: DetectionResult | None,
        simulation_timeout: bool = False,
    ) -> tuple[bool, str, str]:
        if heuristic.result == FilterResult.SUSPICIOUS and heuristic.confidence > 0.9:
            return True, "critical", "block"

        if ml_result and ml_result.is_anomaly and ml_result.confidence > 0.8:
            return True, "high", "block"

        if heuristic.result == FilterResult.SUSPICIOUS:
            if ml_result and ml_result.anomaly_score > 0.5:
                return True, "high", "block"
            return True, "medium", "flag"

        # FIX: Consider simulation timeout - complex transactions that timeout
        # combined with other risk signals should be flagged
        if simulation_timeout:
            if ml_result and ml_result.anomaly_score > 0.3:
                return True, "medium", "flag"
            if len(heuristic.risk_indicators) >= 1:
                return True, "medium", "flag"

        if ml_result and ml_result.is_anomaly:
            if heuristic.result == FilterResult.UNKNOWN:
                return True, "medium", "flag"
            return False, "low", "monitor"

        if len(heuristic.risk_indicators) >= 2:
            return False, "low", "monitor"

        return False, "low", "allow"

    def _calculate_overall_confidence(
        self,
        heuristic: HeuristicResult,
        ml_result: DetectionResult | None,
    ) -> float:
        if ml_result is None:
            return heuristic.confidence

        heuristic_weight = 0.4
        ml_weight = 0.6

        return (
            heuristic.confidence * heuristic_weight +
            ml_result.confidence * ml_weight
        )

    def get_stats(self) -> EngineStats:
        total = self._stats["total_analyzed"]
        avg_latency = (
            self._stats["total_latency_ms"] / total if total > 0 else 0.0
        )

        suspicious = self._stats["suspicious_detected"]
        fp_estimate = 0.01 if suspicious > 0 else 0.0

        return EngineStats(
            total_analyzed=total,
            safe_filtered=self._stats["safe_filtered"],
            suspicious_detected=suspicious,
            ml_analyzed=self._stats["ml_analyzed"],
            avg_latency_ms=avg_latency,
            false_positive_estimate=fp_estimate,
        )

    def reset_stats(self) -> None:
        self._stats = {
            "total_analyzed": 0,
            "safe_filtered": 0,
            "suspicious_detected": 0,
            "ml_analyzed": 0,
            "total_latency_ms": 0.0,
        }

    @classmethod
    def load(cls, model_path: str | Path, rpc_url: str = "") -> InferenceEngine:
        return cls(rpc_url=rpc_url, model_path=model_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Sentinel Inference Engine")
    parser.add_argument("--serve", action="store_true", help="Start gRPC server")
    parser.add_argument("--port", type=int, default=50051, help="Server port")
    parser.add_argument("--rpc", type=str, required=True, help="Ethereum RPC URL")
    parser.add_argument("--model", type=str, help="Path to trained model")

    args = parser.parse_args()

    if args.serve:
        logger.info("gRPC server mode not implemented yet")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

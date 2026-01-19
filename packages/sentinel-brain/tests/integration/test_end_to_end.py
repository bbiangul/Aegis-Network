"""
End-to-end integration tests for Sentinel Brain.

Tests the full pipeline from transaction input to risk signal output.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Skip if required dependencies not available
pytest.importorskip("grpc")


class TestEndToEndPipeline:
    """Test the full inference pipeline.

    Note: These tests require the SignalEngine to support analyze_pending/analyze_batch
    with transaction dicts. The current implementation uses TransactionTrace objects
    which require full trace data from Anvil fork replay. These tests are skipped
    until the simplified API is implemented.
    """

    @pytest.fixture
    def model_path(self):
        """Get path to test model."""
        path = Path(__file__).parent.parent.parent / "models" / "sentinel_model.joblib"
        if not path.exists():
            pytest.skip("Model not found - run training first")
        return str(path)

    @pytest.fixture
    def sample_benign_tx(self):
        """Sample benign transaction."""
        return {
            "hash": "0x" + "a" * 64,
            "from": "0x" + "1" * 40,
            "to": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 Router
            "value": 0,
            "gas": 200000,
            "gasPrice": 50000000000,
            "input": "0x38ed1739" + "0" * 256,  # swapExactTokensForTokens
            "nonce": 100,
        }

    @pytest.fixture
    def sample_suspicious_tx(self):
        """Sample suspicious transaction with flash loan."""
        return {
            "hash": "0x" + "b" * 64,
            "from": "0x" + "2" * 40,
            "to": "0x" + "3" * 40,  # Unknown contract
            "value": 0,
            "gas": 3000000,
            "gasPrice": 100000000000,
            "input": "0x5cffe9de" + "0" * 512,  # flashLoan
            "nonce": 1,
        }

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="SignalEngine.analyze_pending API not yet implemented - requires TransactionTrace")
    async def test_signal_engine_benign_tx(self, model_path, sample_benign_tx):
        """Test signal engine with benign transaction."""
        from sentinel_brain.inference.signal import SignalEngine, RiskLevel

        engine = SignalEngine(model_path=model_path)

        signal = await engine.analyze_pending(sample_benign_tx)

        # Benign swap on known protocol should be low risk
        assert signal.risk_level in [RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM]
        assert signal.risk_score < 0.7
        assert signal.protocol == "uniswap_v2"
        assert signal.operation == "swap"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="SignalEngine.analyze_pending API not yet implemented - requires TransactionTrace")
    async def test_signal_engine_suspicious_tx(self, model_path, sample_suspicious_tx):
        """Test signal engine with suspicious transaction."""
        from sentinel_brain.inference.signal import SignalEngine, RiskLevel

        engine = SignalEngine(model_path=model_path)

        signal = await engine.analyze_pending(sample_suspicious_tx)

        # Flash loan on unknown contract should be flagged
        assert signal.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert "flash_loan_detected" in signal.risk_indicators or signal.risk_score > 0.5

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="SignalEngine.analyze_batch API not yet implemented - requires TransactionTrace")
    async def test_batch_analysis(self, model_path, sample_benign_tx, sample_suspicious_tx):
        """Test batch analysis."""
        from sentinel_brain.inference.signal import SignalEngine

        engine = SignalEngine(model_path=model_path)

        txs = [sample_benign_tx, sample_suspicious_tx]
        signals = await engine.analyze_batch(txs)

        assert len(signals) == 2
        # First should be less risky than second
        assert signals[0].risk_score <= signals[1].risk_score + 0.3  # Allow some variance


class TestHeuristicFilter:
    """Test heuristic pre-filtering."""

    def test_quick_filter_simple_transfer(self):
        """Test quick filter allows simple transfers."""
        from sentinel_brain.models.heuristics import HeuristicFilter
        from sentinel_brain.data.collectors.mempool_listener import PendingTransaction

        filter = HeuristicFilter()
        tx = PendingTransaction(
            hash="0x" + "a" * 64,
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            value=1000000000000000000,  # 1 ETH
            gas=21000,
            gas_price=50000000000,
            max_fee_per_gas=None,
            max_priority_fee_per_gas=None,
            input_data="0x",
            nonce=1,
            chain_id=1,
        )

        # Simple transfer should not need ML analysis
        result = filter.quick_filter(tx)
        assert result == False  # False means "safe, no analysis needed"

    def test_quick_filter_flags_flash_loan(self):
        """Test quick filter flags flash loans for analysis."""
        from sentinel_brain.models.heuristics import HeuristicFilter, FilterResult
        from sentinel_brain.data.collectors.mempool_listener import PendingTransaction

        filter = HeuristicFilter()
        tx = PendingTransaction(
            hash="0x" + "b" * 64,
            from_address="0x" + "1" * 40,
            to_address="0x" + "3" * 40,  # Unknown contract
            value=0,
            gas=2000000,
            gas_price=100000000000,
            max_fee_per_gas=None,
            max_priority_fee_per_gas=None,
            input_data="0x5cffe9de" + "0" * 64,  # flashLoan selector
            nonce=1,
            chain_id=1,
        )

        # Use filter() method for full analysis
        result = filter.filter(tx)
        # High gas + suspicious selector should flag for analysis
        assert result.should_analyze == True
        assert "suspicious_selector" in result.risk_indicators or "high_gas_limit" in result.risk_indicators

    def test_whitelist_known_contract(self):
        """Test whitelisted contracts with safe selectors pass."""
        from sentinel_brain.models.heuristics import HeuristicFilter
        from sentinel_brain.data.collectors.mempool_listener import PendingTransaction

        filter = HeuristicFilter()
        tx = PendingTransaction(
            hash="0x" + "c" * 64,
            from_address="0x" + "1" * 40,
            to_address="0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 Router
            value=0,
            gas=200000,
            gas_price=50000000000,
            max_fee_per_gas=None,
            max_priority_fee_per_gas=None,
            input_data="0xa9059cbb" + "0" * 64,  # transfer - safe selector
            nonce=1,
            chain_id=1,
        )

        # Whitelisted contract + safe selector should not need analysis
        result = filter.quick_filter(tx)
        assert result == False  # False means "safe, no analysis needed"


class TestProtocolFilter:
    """Test protocol-aware filtering."""

    def test_identify_uniswap(self):
        """Test Uniswap protocol identification."""
        from sentinel_brain.models.protocol_filter import ProtocolFilter, Protocol

        filter = ProtocolFilter()
        protocol = filter.identify_protocol("0x7a250d5630b4cf539739df2c5dacb4c659f2488d")

        assert protocol == Protocol.UNISWAP_V2

    def test_identify_swap_operation(self):
        """Test swap operation identification."""
        from sentinel_brain.models.protocol_filter import ProtocolFilter, OperationType

        filter = ProtocolFilter()
        operation = filter.identify_operation("0x38ed1739")  # swapExactTokensForTokens

        assert operation == OperationType.SWAP

    def test_risk_adjustment_known_protocol(self):
        """Test risk adjustment for known protocol."""
        from sentinel_brain.models.protocol_filter import ProtocolFilter
        from sentinel_brain.features.aggregator import AggregatedFeatures
        from sentinel_brain.features.extractors.flash_loan import FlashLoanFeatures
        from sentinel_brain.features.extractors.state_variance import StateVarianceFeatures
        from sentinel_brain.features.extractors.bytecode import BytecodeFeatures
        from sentinel_brain.features.extractors.opcode import OpcodeFeatures

        filter = ProtocolFilter()

        # Create minimal features
        features = AggregatedFeatures(
            flash_loan=FlashLoanFeatures(
                has_flash_loan=False,
                flash_loan_count=0,
                flash_loan_providers=[],
                flash_loan_amounts=[],
                total_borrowed=0,
                has_callback=False,
                callback_selectors=[],
                nested_flash_loans=False,
                repayment_detected=False,
            ),
            state_variance=StateVarianceFeatures(
                total_storage_changes=5,
                unique_contracts_modified=2,
                unique_slots_modified=5,
                balance_slot_changes=2,
                large_value_changes=0,
                max_value_delta=1000000000000000000,
                avg_value_delta=500000000000000000,
                variance_ratio=0.5,
                zero_to_nonzero=1,
                nonzero_to_zero=0,
            ),
            bytecode=BytecodeFeatures(
                bytecode_length=1000,
                bytecode_hash="0x123",
                is_contract=True,
                is_proxy=False,
                proxy_type=None,
                contract_age_blocks=1000000,
                is_verified=True,
                matches_known_exploit=False,
                matched_exploit_id=None,
                jaccard_similarity=0.0,
                has_selfdestruct=False,
                has_delegatecall=False,
                has_create2=False,
                unique_opcodes=50,
            ),
            opcode=OpcodeFeatures(
                total_calls=10,
                call_depth=2,
                delegatecall_count=0,
                staticcall_count=2,
                create_count=0,
                create2_count=0,
                selfdestruct_count=0,
                call_count=8,
                internal_calls=5,
                external_calls=5,
                unique_call_types=2,
                call_value_transfers=1,
                gas_forwarded_ratio=0.8,
                revert_count=0,
            ),
            metadata={"gas_used": 150000},
        )

        # Test with Uniswap swap
        result = filter.filter(
            features,
            original_risk_score=0.6,
            to_address="0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
            input_data="0x38ed1739",
        )

        # Should reduce risk for known protocol + operation
        assert result.adjusted_risk_score < 0.6
        assert result.context.is_known_protocol
        assert result.context.is_known_operation


class TestPersistence:
    """Test database persistence."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        yield db_path

        # Cleanup
        try:
            os.unlink(db_path)
        except Exception:
            pass

    def test_save_and_get_alert(self, temp_db):
        """Test saving and retrieving alerts."""
        from sentinel_brain.persistence import Database, DatabaseConfig, Alert, AlertStatus

        config = DatabaseConfig(sqlite_path=temp_db)
        db = Database(config)
        db.initialize()

        alert = Alert(
            id=str(uuid.uuid4()),
            tx_hash="0x" + "a" * 64,
            created_at=datetime.now(timezone.utc),
            risk_level="high",
            risk_score=0.85,
            confidence=0.9,
            risk_indicators=["flash_loan_detected", "high_gas"],
            protocol="unknown",
            operation="unknown",
            explanation="Suspicious flash loan activity",
            status=AlertStatus.PENDING,
        )

        db.save_alert(alert)
        retrieved = db.get_alert(alert.id)

        assert retrieved is not None
        assert retrieved.tx_hash == alert.tx_hash
        assert retrieved.risk_score == alert.risk_score
        assert retrieved.risk_indicators == alert.risk_indicators

    def test_save_and_get_analysis(self, temp_db):
        """Test saving and retrieving analysis records."""
        from sentinel_brain.persistence import Database, DatabaseConfig, AnalysisRecord

        config = DatabaseConfig(sqlite_path=temp_db)
        db = Database(config)
        db.initialize()

        record = AnalysisRecord(
            id=str(uuid.uuid4()),
            tx_hash="0x" + "b" * 64,
            analyzed_at=datetime.now(timezone.utc),
            risk_level="medium",
            risk_score=0.55,
            raw_risk_score=0.65,
            confidence=0.75,
            heuristic_result="suspicious",
            ml_score=0.6,
            risk_indicators=["high_gas"],
            protocol="uniswap_v2",
            operation="swap",
            risk_adjustment=-0.1,
            latency_ms=25.5,
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            value_wei="1000000000000000000",
            gas=200000,
            input_data_hash="0x123abc",
        )

        db.save_analysis(record)
        retrieved = db.get_analysis_by_tx(record.tx_hash)

        assert retrieved is not None
        assert retrieved.risk_score == record.risk_score
        assert retrieved.protocol == record.protocol

    def test_get_alerts_with_filter(self, temp_db):
        """Test filtering alerts."""
        from sentinel_brain.persistence import Database, DatabaseConfig, Alert, AlertStatus

        config = DatabaseConfig(sqlite_path=temp_db)
        db = Database(config)
        db.initialize()

        # Create alerts with different statuses
        for i, status in enumerate([AlertStatus.PENDING, AlertStatus.CONFIRMED, AlertStatus.PENDING]):
            alert = Alert(
                id=str(uuid.uuid4()),
                tx_hash=f"0x{'a' * 63}{i}",
                created_at=datetime.now(timezone.utc),
                risk_level="high",
                risk_score=0.8,
                confidence=0.9,
                risk_indicators=[],
                protocol="unknown",
                operation="unknown",
                explanation="Test",
                status=status,
            )
            db.save_alert(alert)

        pending = db.get_alerts(status=AlertStatus.PENDING)
        assert len(pending) == 2

        confirmed = db.get_alerts(status=AlertStatus.CONFIRMED)
        assert len(confirmed) == 1


class TestModelPerformance:
    """Test model performance benchmarks."""

    @pytest.fixture
    def model_path(self):
        """Get path to test model."""
        path = Path(__file__).parent.parent.parent / "models" / "sentinel_model.joblib"
        if not path.exists():
            pytest.skip("Model not found - run training first")
        return str(path)

    def test_model_loads(self, model_path):
        """Test model loads successfully."""
        from sentinel_brain.models.isolation_forest import IsolationForestDetector

        model = IsolationForestDetector.load(model_path)
        assert model is not None
        assert model.model is not None

    def test_inference_latency(self, model_path):
        """Test inference latency is acceptable."""
        import time
        from sentinel_brain.models.isolation_forest import IsolationForestDetector

        model = IsolationForestDetector.load(model_path)

        # Generate random feature vector
        features = np.random.rand(43)

        # Measure latency over multiple runs
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            model.predict_single(features)
            latencies.append((time.perf_counter() - start) * 1000)

        avg_latency = np.mean(latencies)
        p95_latency = np.percentile(latencies, 95)

        # Assert reasonable latency (< 10ms average, < 20ms p95)
        assert avg_latency < 10, f"Average latency too high: {avg_latency:.2f}ms"
        assert p95_latency < 20, f"P95 latency too high: {p95_latency:.2f}ms"


class TestExploitRegistry:
    """Test exploit registry functionality."""

    def test_registry_loads(self):
        """Test exploit registry loads successfully."""
        from sentinel_brain.data.exploits.registry import ExploitRegistry

        registry = ExploitRegistry()
        exploits = registry.get_all()

        assert len(exploits) > 0

    def test_get_high_priority_exploits(self):
        """Test getting high priority exploits."""
        from sentinel_brain.data.exploits.registry import ExploitRegistry, TrainingPriority

        registry = ExploitRegistry()
        high_priority = registry.get_by_priority(TrainingPriority.P0_CRITICAL)

        assert len(high_priority) > 0
        for exploit in high_priority:
            assert exploit.training_priority == TrainingPriority.P0_CRITICAL

    def test_get_by_attack_vector(self):
        """Test getting exploits by attack vector."""
        from sentinel_brain.data.exploits.registry import ExploitRegistry, AttackVector

        registry = ExploitRegistry()
        flash_loan_attacks = registry.get_by_attack_vector(AttackVector.FLASH_LOAN)

        assert len(flash_loan_attacks) > 0
        for exploit in flash_loan_attacks:
            assert exploit.attack_vector == AttackVector.FLASH_LOAN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

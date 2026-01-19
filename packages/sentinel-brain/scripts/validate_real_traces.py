#!/usr/bin/env python3
"""Validate model detection on real exploit traces."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sentinel_brain.data.collectors.fork_replayer import (
    TransactionTrace,
    TraceLog,
    TraceCall,
    StorageChange,
)
from sentinel_brain.features.aggregator import FeatureAggregator
from sentinel_brain.models.isolation_forest import IsolationForestDetector
from sentinel_brain.models.heuristics import HeuristicFilter, FilterResult


def load_trace_from_json(path: Path) -> TransactionTrace:
    """Load a TransactionTrace from a JSON file."""
    with open(path) as f:
        data = json.load(f)

    logs = [
        TraceLog(
            address=log["address"],
            topics=log["topics"],
            data=log["data"],
        )
        for log in data.get("logs", [])
    ]

    storage_changes = [
        StorageChange(
            address=sc["address"],
            slot=sc["slot"],
            previous_value=sc.get("previous", "0x0"),
            new_value=sc.get("new", "0x0"),
        )
        for sc in data.get("storage_changes", [])
    ]

    return TransactionTrace(
        tx_hash=data["tx_hash"],
        block_number=data["block_number"],
        from_address=data["from_address"],
        to_address=data.get("to_address"),
        value=data.get("value", 0),
        gas_used=data.get("gas_used", 0),
        gas_price=data.get("gas_price", 0),
        input_data=data.get("input_data", ""),
        status=data.get("status", True),
        logs=logs,
        call_trace=None,
        storage_changes=storage_changes,
        opcodes=data.get("opcodes", {}),
        contracts_called=data.get("contracts_called", []),
        created_contracts=data.get("created_contracts", []),
        selfdestruct_contracts=data.get("selfdestruct_contracts", []),
    )


def make_decision(heuristic, ml_result):
    """Replicate inference engine decision logic."""
    if heuristic.result == FilterResult.SUSPICIOUS and heuristic.confidence > 0.9:
        return True, "critical", "BLOCK"

    if ml_result and ml_result.is_anomaly and ml_result.confidence > 0.8:
        return True, "high", "BLOCK"

    if heuristic.result == FilterResult.SUSPICIOUS:
        if ml_result and ml_result.anomaly_score > 0.5:
            return True, "high", "BLOCK"
        return True, "medium", "FLAG"

    if ml_result and ml_result.is_anomaly:
        if heuristic.result == FilterResult.UNKNOWN:
            return True, "medium", "FLAG"
        return False, "low", "MONITOR"

    return False, "low", "ALLOW"


async def validate_trace(
    trace: TransactionTrace,
    aggregator: FeatureAggregator,
    model: IsolationForestDetector,
    heuristic_filter: HeuristicFilter,
    name: str,
) -> dict:
    """Validate a single trace against the model."""
    features = await aggregator.extract_from_trace(trace)
    ml_result = model.predict(features)
    heuristic = heuristic_filter.filter_with_features(features)

    flash_loan = features.flash_loan
    state_var = features.state_variance
    opcode = features.opcode

    # Get final decision
    is_suspicious, risk_level, action = make_decision(heuristic, ml_result)

    print(f"\n{'='*60}")
    print(f"Exploit: {name}")
    print(f"TX: {trace.tx_hash}")
    print(f"Block: {trace.block_number}")
    print(f"Logs: {len(trace.logs)}, Gas: {trace.gas_used:,}")
    print(f"\nFlash Loan Features:")
    print(f"  - has_flash_loan: {flash_loan.has_flash_loan}")
    print(f"  - providers: {flash_loan.flash_loan_providers}")
    print(f"  - total_borrowed: {flash_loan.total_borrowed / 1e18:.2f} ETH equiv")
    print(f"  - has_callback: {flash_loan.has_callback}")
    print(f"  - repayment_detected: {flash_loan.repayment_detected}")
    print(f"\nState Variance Features:")
    print(f"  - storage_changes: {state_var.total_storage_changes}")
    print(f"  - unique_contracts: {state_var.unique_contracts_modified}")
    print(f"  - large_changes: {state_var.large_value_changes}")
    print(f"  - max_delta: {state_var.max_value_delta / 1e18:.2f} ETH equiv")
    print(f"\nOpcode Features:")
    print(f"  - total_calls: {opcode.total_calls}")
    print(f"  - call_depth: {opcode.call_depth}")
    print(f"  - external_calls: {opcode.external_calls}")
    print(f"  - call_value_transfers: {opcode.call_value_transfers}")
    print(f"\nHeuristic Analysis:")
    print(f"  - result: {heuristic.result.value}")
    print(f"  - confidence: {heuristic.confidence:.2f}")
    print(f"  - risk_indicators: {heuristic.risk_indicators}")
    print(f"\nML Detection:")
    print(f"  - is_anomaly: {ml_result.is_anomaly}")
    print(f"  - anomaly_score: {ml_result.anomaly_score:.4f}")
    print(f"  - confidence: {ml_result.confidence:.4f}")
    print(f"\n>>> DECISION: {action} (risk: {risk_level})")

    return {
        "name": name,
        "tx_hash": trace.tx_hash,
        "detected": ml_result.is_anomaly,
        "anomaly_score": ml_result.anomaly_score,
        "action": action,
        "risk_level": risk_level,
        "has_flash_loan": flash_loan.has_flash_loan,
        "total_borrowed": flash_loan.total_borrowed,
    }


async def main():
    traces_dir = Path(__file__).parent.parent / "data" / "traces"
    model_path = Path(__file__).parent.parent / "models" / "sentinel_model.joblib"

    if not model_path.exists():
        print(f"Model not found at {model_path}")
        return

    trace_files = list(traces_dir.glob("*.json"))
    if not trace_files:
        print(f"No traces found in {traces_dir}")
        return

    print(f"Loading model from {model_path}")
    model = IsolationForestDetector.load(model_path)
    aggregator = FeatureAggregator()
    heuristic_filter = HeuristicFilter()

    print(f"\nFound {len(trace_files)} trace files")
    print("="*60)

    results = []
    for trace_file in sorted(trace_files):
        name = trace_file.stem.replace("_", " ").title()
        try:
            trace = load_trace_from_json(trace_file)
            result = await validate_trace(trace, aggregator, model, heuristic_filter, name)
            results.append(result)
        except Exception as e:
            print(f"\nError processing {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append({"name": name, "detected": False, "action": "ERROR", "error": str(e)})

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    blocked = sum(1 for r in results if r.get("action") == "BLOCK")
    flagged = sum(1 for r in results if r.get("action") == "FLAG")
    detected = sum(1 for r in results if r.get("detected", False))
    total = len(results)

    print(f"\nML Detection Rate: {detected}/{total} ({100*detected/total:.1f}%)")
    print(f"Would BLOCK: {blocked}/{total}")
    print(f"Would FLAG: {flagged}/{total}")
    print("\nResults by exploit:")
    for r in results:
        action = r.get("action", "UNKNOWN")
        score = r.get("anomaly_score", 0)
        risk = r.get("risk_level", "unknown")
        print(f"  - {r['name']}: {action} (score: {score:.4f}, risk: {risk})")

    if blocked == total:
        print("\n100% would trigger BLOCK (pause)!")
    elif blocked + flagged == total:
        print(f"\nAll exploits detected: {blocked} BLOCK + {flagged} FLAG")
    else:
        print(f"\nMissed {total - blocked - flagged} exploits")


if __name__ == "__main__":
    asyncio.run(main())

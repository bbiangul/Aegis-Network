#!/usr/bin/env python3
"""
Validate signal-based detection on real exploit traces.

This demonstrates the production-safe approach: signals instead of pauses.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sentinel_brain.data.collectors.fork_replayer import (
    TransactionTrace,
    TraceLog,
    StorageChange,
)
from sentinel_brain.inference.signal import SignalEngine, RiskLevel, console_alert


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

    print("=" * 70)
    print("SENTINEL SIGNAL ENGINE - EXPLOIT VALIDATION")
    print("=" * 70)
    print(f"\nLoading model from {model_path}")

    # Initialize signal engine with console alerts for HIGH+ risks
    engine = SignalEngine(
        model_path=model_path,
        alert_callbacks=[console_alert],
        min_alert_level=RiskLevel.HIGH,
    )

    print(f"Found {len(trace_files)} trace files\n")

    results = []
    for trace_file in sorted(trace_files):
        name = trace_file.stem.replace("_", " ").title()
        print("-" * 70)
        print(f"Analyzing: {name}")
        print("-" * 70)

        try:
            trace = load_trace_from_json(trace_file)
            signal = await engine.analyze_async(trace)

            print(f"\nRisk Level: {signal.risk_level.value.upper()}")
            print(f"Risk Score: {signal.risk_score:.2%}")
            print(f"Confidence: {signal.confidence:.2%}")
            print(f"\nRisk Indicators: {signal.risk_indicators}")
            print(f"\nExplanation: {signal.explanation}")
            print(f"\nRecommendation: {signal.recommended_action}")
            print(f"\nLatency: {signal.latency_ms:.2f}ms")

            results.append({
                "name": name,
                "risk_level": signal.risk_level.value,
                "risk_score": signal.risk_score,
                "confidence": signal.confidence,
                "would_alert": signal.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL],
            })

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "name": name,
                "risk_level": "error",
                "risk_score": 0,
                "would_alert": False,
            })

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    stats = engine.get_stats()
    print(f"\nTotal Analyzed: {stats['total_analyzed']}")
    print(f"Average Latency: {stats['avg_latency_ms']:.2f}ms")
    print(f"\nBy Risk Level:")
    for level, count in stats["by_risk_level"].items():
        print(f"  {level.upper()}: {count}")

    print(f"\nAlert Rate: {stats['alert_rate']:.2%}")

    # Results table
    print("\n" + "-" * 70)
    print(f"{'Exploit':<25} {'Risk Level':<12} {'Score':<10} {'Alert?':<8}")
    print("-" * 70)

    alerts_triggered = 0
    for r in results:
        alert = "YES" if r.get("would_alert") else "no"
        if r.get("would_alert"):
            alerts_triggered += 1
        print(f"{r['name']:<25} {r['risk_level'].upper():<12} {r['risk_score']:.2%}     {alert:<8}")

    print("-" * 70)
    print(f"\nExploits that would trigger alerts: {alerts_triggered}/{len(results)}")

    if alerts_triggered == len(results):
        print("\n✅ All exploits would trigger alerts!")
    else:
        print(f"\n⚠️  {len(results) - alerts_triggered} exploits would only be logged (not alerted)")


if __name__ == "__main__":
    asyncio.run(main())

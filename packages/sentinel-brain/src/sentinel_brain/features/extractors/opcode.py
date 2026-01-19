from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sentinel_brain.data.collectors.fork_replayer import TransactionTrace, TraceCall


DANGEROUS_OPCODES = {
    "DELEGATECALL": 0xf4,
    "CALLCODE": 0xf2,
    "SELFDESTRUCT": 0xff,
    "CREATE": 0xf0,
    "CREATE2": 0xf5,
    "STATICCALL": 0xfa,
    "CALL": 0xf1,
}

MEMORY_OPCODES = {
    "MLOAD": 0x51,
    "MSTORE": 0x52,
    "MSTORE8": 0x53,
    "MSIZE": 0x59,
}

STORAGE_OPCODES = {
    "SLOAD": 0x54,
    "SSTORE": 0x55,
}

CONTROL_FLOW_OPCODES = {
    "JUMP": 0x56,
    "JUMPI": 0x57,
    "JUMPDEST": 0x5b,
}

CALL_TYPE_OPCODES = {
    "CALL",
    "STATICCALL",
    "DELEGATECALL",
    "CALLCODE",
    "CREATE",
    "CREATE2",
}


@dataclass
class OpcodeFeatures:
    total_calls: int
    call_depth: int
    delegatecall_count: int
    staticcall_count: int
    create_count: int
    create2_count: int
    selfdestruct_count: int
    call_count: int
    internal_calls: int
    external_calls: int
    unique_call_types: int
    call_value_transfers: int
    gas_forwarded_ratio: float
    revert_count: int
    opcode_frequency: dict[str, int] = field(default_factory=dict)

    def to_vector(self) -> list[float]:
        return [
            float(self.total_calls),
            float(self.call_depth),
            float(self.delegatecall_count),
            float(self.staticcall_count),
            float(self.create_count),
            float(self.create2_count),
            float(self.selfdestruct_count),
            float(self.call_count),
            float(self.internal_calls),
            float(self.external_calls),
            float(self.unique_call_types),
            float(self.call_value_transfers),
            self.gas_forwarded_ratio,
            float(self.revert_count),
        ]


class OpcodeExtractor:
    def __init__(self) -> None:
        self.dangerous_opcodes = set(DANGEROUS_OPCODES.keys())

    def extract(self, trace: TransactionTrace) -> OpcodeFeatures:
        if not trace.call_trace:
            if trace.opcodes:
                return self._from_opcode_counts(trace.opcodes)
            if trace.logs:
                return self._estimate_from_logs(trace.logs, trace.gas_used)
            return self._empty_features()

        stats = self._analyze_call_tree(trace.call_trace)

        opcode_freq = trace.opcodes.copy()
        for call_type, count in stats["call_types"].items():
            opcode_freq[call_type] = opcode_freq.get(call_type, 0) + count

        return OpcodeFeatures(
            total_calls=stats["total_calls"],
            call_depth=stats["max_depth"],
            delegatecall_count=stats["call_types"].get("DELEGATECALL", 0),
            staticcall_count=stats["call_types"].get("STATICCALL", 0),
            create_count=stats["call_types"].get("CREATE", 0),
            create2_count=stats["call_types"].get("CREATE2", 0),
            selfdestruct_count=stats["call_types"].get("SELFDESTRUCT", 0),
            call_count=stats["call_types"].get("CALL", 0),
            internal_calls=stats["internal_calls"],
            external_calls=stats["external_calls"],
            unique_call_types=len(stats["call_types"]),
            call_value_transfers=stats["value_transfers"],
            gas_forwarded_ratio=stats["gas_ratio"],
            revert_count=stats["reverts"],
            opcode_frequency=opcode_freq,
        )

    def extract_from_opcodes(self, opcodes: dict[str, int]) -> OpcodeFeatures:
        return self._from_opcode_counts(opcodes)

    def analyze_call_pattern(self, trace: TransactionTrace) -> dict[str, Any]:
        if not trace.call_trace:
            return {"pattern": "simple", "risk_score": 0.0}

        stats = self._analyze_call_tree(trace.call_trace)

        risk_score = 0.0

        if stats["call_types"].get("DELEGATECALL", 0) > 0:
            risk_score += 0.3

        if stats["call_types"].get("CREATE2", 0) > 0:
            risk_score += 0.2

        if stats["call_types"].get("SELFDESTRUCT", 0) > 0:
            risk_score += 0.4

        if stats["max_depth"] > 5:
            risk_score += 0.1 * (stats["max_depth"] - 5)

        if stats["total_calls"] > 20:
            risk_score += 0.1

        pattern = self._classify_pattern(stats)

        return {
            "pattern": pattern,
            "risk_score": min(risk_score, 1.0),
            "stats": stats,
        }

    def _analyze_call_tree(self, call: TraceCall, depth: int = 0) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "total_calls": 1,
            "max_depth": depth,
            "call_types": {},
            "internal_calls": 0,
            "external_calls": 0,
            "value_transfers": 0,
            "total_gas": call.gas,
            "used_gas": call.gas_used,
            "reverts": 0,
        }

        call_type = call.call_type.upper()
        stats["call_types"][call_type] = 1

        if call.value > 0:
            stats["value_transfers"] = 1

        if call_type in ("CALL", "STATICCALL", "DELEGATECALL", "CALLCODE"):
            stats["external_calls"] = 1
        else:
            stats["internal_calls"] = 1

        for child in call.children:
            child_stats = self._analyze_call_tree(child, depth + 1)

            stats["total_calls"] += child_stats["total_calls"]
            stats["max_depth"] = max(stats["max_depth"], child_stats["max_depth"])
            stats["internal_calls"] += child_stats["internal_calls"]
            stats["external_calls"] += child_stats["external_calls"]
            stats["value_transfers"] += child_stats["value_transfers"]
            stats["total_gas"] += child_stats["total_gas"]
            stats["used_gas"] += child_stats["used_gas"]
            stats["reverts"] += child_stats["reverts"]

            for ct, count in child_stats["call_types"].items():
                stats["call_types"][ct] = stats["call_types"].get(ct, 0) + count

        stats["gas_ratio"] = stats["used_gas"] / stats["total_gas"] if stats["total_gas"] > 0 else 0.0

        return stats

    def _from_opcode_counts(self, opcodes: dict[str, int]) -> OpcodeFeatures:
        total = sum(opcodes.values())

        return OpcodeFeatures(
            total_calls=total,
            call_depth=0,
            delegatecall_count=opcodes.get("DELEGATECALL", 0),
            staticcall_count=opcodes.get("STATICCALL", 0),
            create_count=opcodes.get("CREATE", 0),
            create2_count=opcodes.get("CREATE2", 0),
            selfdestruct_count=opcodes.get("SELFDESTRUCT", 0),
            call_count=opcodes.get("CALL", 0),
            internal_calls=0,
            external_calls=sum(opcodes.get(op, 0) for op in CALL_TYPE_OPCODES),
            unique_call_types=len([k for k in opcodes if k in CALL_TYPE_OPCODES]),
            call_value_transfers=0,
            gas_forwarded_ratio=0.0,
            revert_count=opcodes.get("REVERT", 0),
            opcode_frequency=opcodes,
        )

    def _classify_pattern(self, stats: dict[str, Any]) -> str:
        call_types = stats["call_types"]

        if call_types.get("SELFDESTRUCT", 0) > 0:
            return "destructive"

        if call_types.get("CREATE2", 0) > 0 and call_types.get("DELEGATECALL", 0) > 0:
            return "metamorphic"

        if call_types.get("DELEGATECALL", 0) > 2:
            return "proxy_chain"

        if stats["total_calls"] > 50:
            return "complex_multicall"

        if stats["max_depth"] > 10:
            return "deep_recursion"

        if stats["value_transfers"] > 5:
            return "multi_transfer"

        if call_types.get("CALL", 0) > 10:
            return "batch_calls"

        return "standard"

    def get_risk_indicators(self, features: OpcodeFeatures) -> list[str]:
        indicators: list[str] = []

        if features.delegatecall_count > 0:
            indicators.append("uses_delegatecall")

        if features.create2_count > 0:
            indicators.append("uses_create2")

        if features.selfdestruct_count > 0:
            indicators.append("uses_selfdestruct")

        if features.call_depth > 10:
            indicators.append("deep_call_stack")

        if features.total_calls > 50:
            indicators.append("high_call_count")

        if features.call_value_transfers > 5:
            indicators.append("multiple_value_transfers")

        if features.gas_forwarded_ratio > 0.95:
            indicators.append("high_gas_forwarding")

        return indicators

    def _estimate_from_logs(self, logs: list, gas_used: int) -> OpcodeFeatures:
        """Estimate opcode features from transaction logs when call trace is unavailable."""
        from sentinel_brain.data.collectors.fork_replayer import TraceLog

        unique_addresses: set[str] = set()
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        transfer_count = 0

        for log in logs:
            if isinstance(log, TraceLog):
                unique_addresses.add(log.address.lower())
                topics = log.topics
            else:
                unique_addresses.add(log.get("address", "").lower())
                topics = log.get("topics", [])

            if topics:
                topic0 = topics[0] if isinstance(topics[0], str) else topics[0].hex()
                if topic0 == transfer_topic:
                    transfer_count += 1

        estimated_calls = len(unique_addresses)
        estimated_depth = min(estimated_calls // 3, 10) if estimated_calls > 3 else 1

        gas_ratio = 0.8 if gas_used > 500000 else 0.5

        return OpcodeFeatures(
            total_calls=estimated_calls,
            call_depth=estimated_depth,
            delegatecall_count=0,
            staticcall_count=0,
            create_count=0,
            create2_count=0,
            selfdestruct_count=0,
            call_count=estimated_calls,
            internal_calls=0,
            external_calls=estimated_calls,
            unique_call_types=1 if estimated_calls > 0 else 0,
            call_value_transfers=transfer_count,
            gas_forwarded_ratio=gas_ratio,
            revert_count=0,
            opcode_frequency={},
        )

    def _empty_features(self) -> OpcodeFeatures:
        """Return empty opcode features."""
        return OpcodeFeatures(
            total_calls=0,
            call_depth=0,
            delegatecall_count=0,
            staticcall_count=0,
            create_count=0,
            create2_count=0,
            selfdestruct_count=0,
            call_count=0,
            internal_calls=0,
            external_calls=0,
            unique_call_types=0,
            call_value_transfers=0,
            gas_forwarded_ratio=0.0,
            revert_count=0,
            opcode_frequency={},
        )

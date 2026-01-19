from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel_brain.data.collectors.fork_replayer import TransactionTrace, StorageChange


BALANCE_SLOTS = {
    "0x0000000000000000000000000000000000000000000000000000000000000000",
    "0x0000000000000000000000000000000000000000000000000000000000000001",
    "0x0000000000000000000000000000000000000000000000000000000000000002",
    "0x0000000000000000000000000000000000000000000000000000000000000003",
    "0x0000000000000000000000000000000000000000000000000000000000000004",
    "0x0000000000000000000000000000000000000000000000000000000000000005",
}

RESERVE_KEYWORDS = ["reserve", "balance", "totalSupply", "liquidity"]


@dataclass
class StateVarianceFeatures:
    total_storage_changes: int
    unique_contracts_modified: int
    unique_slots_modified: int
    balance_slot_changes: int
    large_value_changes: int
    max_value_delta: int
    avg_value_delta: float
    variance_ratio: float
    zero_to_nonzero: int
    nonzero_to_zero: int

    def to_vector(self) -> list[float]:
        return [
            float(self.total_storage_changes),
            float(self.unique_contracts_modified),
            float(self.unique_slots_modified),
            float(self.balance_slot_changes),
            float(self.large_value_changes),
            float(self.max_value_delta) / 1e18 if self.max_value_delta > 0 else 0.0,
            self.avg_value_delta / 1e18 if self.avg_value_delta > 0 else 0.0,
            self.variance_ratio,
            float(self.zero_to_nonzero),
            float(self.nonzero_to_zero),
        ]


class StateVarianceExtractor:
    def __init__(self, large_change_threshold: int = 10**18):
        self.large_change_threshold = large_change_threshold

    def extract(self, trace: TransactionTrace) -> StateVarianceFeatures:
        changes = trace.storage_changes

        if not changes:
            if trace.logs:
                return self._extract_from_trace_logs(trace.logs)
            return self._empty_features()

        contracts: set[str] = set()
        slots: set[str] = set()
        deltas: list[int] = []
        balance_changes = 0
        large_changes = 0
        zero_to_nonzero = 0
        nonzero_to_zero = 0

        for change in changes:
            contracts.add(change.address.lower())
            slots.add(f"{change.address}:{change.slot}")

            prev_val = self._hex_to_int(change.previous_value)
            new_val = self._hex_to_int(change.new_value)
            delta = abs(new_val - prev_val)
            deltas.append(delta)

            if self._is_balance_slot(change.slot):
                balance_changes += 1

            if delta >= self.large_change_threshold:
                large_changes += 1

            if prev_val == 0 and new_val != 0:
                zero_to_nonzero += 1
            elif prev_val != 0 and new_val == 0:
                nonzero_to_zero += 1

        max_delta = max(deltas) if deltas else 0
        avg_delta = sum(deltas) / len(deltas) if deltas else 0.0

        variance_ratio = self._calculate_variance_ratio(deltas)

        return StateVarianceFeatures(
            total_storage_changes=len(changes),
            unique_contracts_modified=len(contracts),
            unique_slots_modified=len(slots),
            balance_slot_changes=balance_changes,
            large_value_changes=large_changes,
            max_value_delta=max_delta,
            avg_value_delta=avg_delta,
            variance_ratio=variance_ratio,
            zero_to_nonzero=zero_to_nonzero,
            nonzero_to_zero=nonzero_to_zero,
        )

    def extract_from_logs(self, logs: list[dict[str, Any]]) -> StateVarianceFeatures:
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

        contracts: set[str] = set()
        transfer_count = 0
        amounts: list[int] = []

        for log in logs:
            contracts.add(log.get("address", "").lower())

            topics = log.get("topics", [])
            if topics and topics[0] == transfer_topic:
                transfer_count += 1
                data = log.get("data", "0x")
                if len(data) >= 66:
                    try:
                        amount = int(data[2:66], 16)
                        amounts.append(amount)
                    except ValueError:
                        pass

        max_amount = max(amounts) if amounts else 0
        avg_amount = sum(amounts) / len(amounts) if amounts else 0.0
        variance_ratio = self._calculate_variance_ratio(amounts)

        return StateVarianceFeatures(
            total_storage_changes=transfer_count,
            unique_contracts_modified=len(contracts),
            unique_slots_modified=transfer_count,
            balance_slot_changes=transfer_count,
            large_value_changes=sum(1 for a in amounts if a >= self.large_change_threshold),
            max_value_delta=max_amount,
            avg_value_delta=avg_amount,
            variance_ratio=variance_ratio,
            zero_to_nonzero=0,
            nonzero_to_zero=0,
        )

    def _extract_from_trace_logs(self, logs: list) -> StateVarianceFeatures:
        """Extract state variance features from TraceLog objects."""
        from sentinel_brain.data.collectors.fork_replayer import TraceLog

        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

        contracts: set[str] = set()
        transfer_count = 0
        amounts: list[int] = []

        for log in logs:
            if isinstance(log, TraceLog):
                contracts.add(log.address.lower())
                topics = log.topics
                data = log.data
            else:
                contracts.add(log.get("address", "").lower())
                topics = log.get("topics", [])
                data = log.get("data", "0x")

            if topics:
                topic0 = topics[0] if isinstance(topics[0], str) else topics[0].hex()
                if topic0 == transfer_topic:
                    transfer_count += 1
                    if len(data) >= 66:
                        try:
                            amount_hex = data[2:66] if data.startswith("0x") else data[:64]
                            amount = int(amount_hex, 16)
                            amounts.append(amount)
                        except ValueError:
                            pass

        max_amount = max(amounts) if amounts else 0
        avg_amount = sum(amounts) / len(amounts) if amounts else 0.0
        variance_ratio = self._calculate_variance_ratio(amounts)

        return StateVarianceFeatures(
            total_storage_changes=transfer_count,
            unique_contracts_modified=len(contracts),
            unique_slots_modified=transfer_count,
            balance_slot_changes=transfer_count,
            large_value_changes=sum(1 for a in amounts if a >= self.large_change_threshold),
            max_value_delta=max_amount,
            avg_value_delta=avg_amount,
            variance_ratio=variance_ratio,
            zero_to_nonzero=0,
            nonzero_to_zero=0,
        )

    def calculate_slippage(
        self,
        input_amount: int,
        output_amount: int,
        expected_rate: float,
    ) -> float:
        if input_amount == 0 or expected_rate == 0:
            return 0.0

        expected_output = input_amount * expected_rate
        actual_slippage = (expected_output - output_amount) / expected_output

        return abs(actual_slippage)

    def detect_large_reserve_change(
        self,
        reserve_before: int,
        reserve_after: int,
        threshold: float = 0.20,
    ) -> bool:
        if reserve_before == 0:
            return reserve_after > 0

        change_ratio = abs(reserve_after - reserve_before) / reserve_before
        return change_ratio >= threshold

    def _empty_features(self) -> StateVarianceFeatures:
        return StateVarianceFeatures(
            total_storage_changes=0,
            unique_contracts_modified=0,
            unique_slots_modified=0,
            balance_slot_changes=0,
            large_value_changes=0,
            max_value_delta=0,
            avg_value_delta=0.0,
            variance_ratio=0.0,
            zero_to_nonzero=0,
            nonzero_to_zero=0,
        )

    def _hex_to_int(self, hex_str: str) -> int:
        if not hex_str or hex_str == "0x":
            return 0
        try:
            return int(hex_str, 16)
        except ValueError:
            return 0

    def _is_balance_slot(self, slot: str) -> bool:
        normalized = slot.lower()
        if normalized in BALANCE_SLOTS:
            return True

        try:
            slot_int = int(normalized, 16)
            return slot_int < 10
        except ValueError:
            return False

    def _calculate_variance_ratio(self, values: list[int]) -> float:
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        if mean == 0:
            return 0.0

        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5

        return std_dev / mean

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel_brain.data.collectors.fork_replayer import TransactionTrace, TraceCall


FLASH_LOAN_SIGNATURES = {
    "0x5cffe9de": "flashLoan(address,address,uint256,bytes)",
    "0xab9c4b5d": "flashLoan(address,address[],uint256[],uint256[],address,bytes,uint16)",
    "0xe0232b42": "flashLoan(address,uint256,bytes)",
    "0xc1a8a1f5": "flash(address,uint256,uint256,bytes)",
    "0x490e6cbc": "flash(address,address,uint256,uint256,bytes)",
    "0x9c3f1e90": "flashLoan(uint256,bytes)",
    "0xd9d98ce4": "flashBorrow(address,uint256)",
    "0x35ea6a75": "flashLoan(address,address,uint256,bytes)",
}

FLASH_LOAN_PROVIDERS = {
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9": "aave_v2",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "aave_v3",
    "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "uniswap_v2",
    "0x1f98431c8ad98523631ae4a59f267346ea31f984": "uniswap_v3",
    "0xba12222222228d8ba445958a75a0704d566bf2c8": "balancer",
    "0x6bdC1FCB2F13d1bA9D26ccEc3983d5D4bf318f57": "dydx",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "weth",
}

CALLBACK_SIGNATURES = {
    "0x23e30c8b": "onFlashLoan(address,address,uint256,uint256,bytes)",
    "0xee872558": "executeOperation(address[],uint256[],uint256[],address,bytes)",
    "0x920f5c84": "uniswapV3FlashCallback(uint256,uint256,bytes)",
    "0xfa461e33": "uniswapV3SwapCallback(int256,int256,bytes)",
    "0x10d1e85c": "pancakeV3SwapCallback(int256,int256,bytes)",
    "0x84800812": "receiveFlashLoan(address[],uint256[],uint256[],bytes)",
}

FLASH_LOAN_EVENT_TOPICS = {
    "0x631042c832b07452973831137f2d73e395028b44b250dedc5abb0ee766e168ac": "aave_v2_flashloan",
    "0xefefaba5e921573100900a3ad9cf29f222d995fb3b6045797eaea7521f5de7a0": "aave_v3_flashloan",
    "0x0d7d75e01ab95780d3cd1c8ec0dd6c2ce19f3a05cdb8d28c4c21e1e1d2b0c92a": "balancer_flashloan",
    "0x76e3a82f8c87c7f3bd4c86ab5f5e2769efb99a8746b0a5c9b73d86db9d0af09e": "dydx_flashloan",
}


@dataclass
class FlashLoanFeatures:
    has_flash_loan: bool
    flash_loan_count: int
    flash_loan_providers: list[str]
    flash_loan_amounts: list[int]
    total_borrowed: int
    has_callback: bool
    callback_selectors: list[str]
    nested_flash_loans: bool
    repayment_detected: bool

    def to_vector(self) -> list[float]:
        return [
            1.0 if self.has_flash_loan else 0.0,
            float(self.flash_loan_count),
            float(len(self.flash_loan_providers)),
            float(self.total_borrowed) / 1e18 if self.total_borrowed > 0 else 0.0,
            1.0 if self.has_callback else 0.0,
            float(len(self.callback_selectors)),
            1.0 if self.nested_flash_loans else 0.0,
            1.0 if self.repayment_detected else 0.0,
        ]


class FlashLoanExtractor:
    def __init__(self) -> None:
        self.flash_loan_sigs = set(FLASH_LOAN_SIGNATURES.keys())
        self.callback_sigs = set(CALLBACK_SIGNATURES.keys())
        self.provider_addresses = {k.lower(): v for k, v in FLASH_LOAN_PROVIDERS.items()}
        self.flash_loan_event_topics = FLASH_LOAN_EVENT_TOPICS

    def extract(self, trace: TransactionTrace) -> FlashLoanFeatures:
        flash_loan_calls: list[dict[str, Any]] = []
        callback_calls: list[str] = []
        providers: set[str] = set()
        amounts: list[int] = []

        if trace.call_trace:
            self._analyze_call_tree(
                trace.call_trace,
                flash_loan_calls,
                callback_calls,
                providers,
                amounts,
                depth=0,
            )

        log_flash_loans = self._detect_flash_loans_from_logs(trace.logs)
        for fl in log_flash_loans:
            providers.add(fl["provider"])
            if fl["amount"] > 0:
                amounts.append(fl["amount"])

        input_selector = trace.input_data[:10] if len(trace.input_data) >= 10 else ""
        has_flash_loan_input = input_selector in self.flash_loan_sigs

        has_flash_loan = bool(flash_loan_calls) or has_flash_loan_input or bool(log_flash_loans)
        flash_loan_count = max(len(flash_loan_calls), len(log_flash_loans))
        nested = self._detect_nested_flash_loans(flash_loan_calls)
        repayment = self._detect_repayment(trace) or self._detect_repayment_from_logs(trace.logs)

        return FlashLoanFeatures(
            has_flash_loan=has_flash_loan,
            flash_loan_count=flash_loan_count,
            flash_loan_providers=list(providers),
            flash_loan_amounts=amounts,
            total_borrowed=sum(amounts),
            has_callback=bool(callback_calls) or has_flash_loan,
            callback_selectors=callback_calls,
            nested_flash_loans=nested,
            repayment_detected=repayment,
        )

    def _detect_flash_loans_from_logs(self, logs: list) -> list[dict[str, Any]]:
        flash_loans = []
        for log in logs:
            if not log.topics:
                continue
            topic0 = log.topics[0] if isinstance(log.topics[0], str) else log.topics[0].hex()
            if topic0 in self.flash_loan_event_topics:
                provider = self.flash_loan_event_topics[topic0]
                amount = self._extract_amount_from_log_data(log.data)
                flash_loans.append({"provider": provider, "amount": amount, "address": log.address})
        return flash_loans

    def _extract_amount_from_log_data(self, data: str) -> int:
        if len(data) < 66:
            return 0
        try:
            amount_hex = data[2:66] if data.startswith("0x") else data[:64]
            return int(amount_hex, 16)
        except ValueError:
            return 0

    def _detect_repayment_from_logs(self, logs: list) -> bool:
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        transfer_count = 0
        for log in logs:
            if not log.topics:
                continue
            topic0 = log.topics[0] if isinstance(log.topics[0], str) else log.topics[0].hex()
            if topic0 == transfer_topic:
                transfer_count += 1
        return transfer_count >= 2

    def extract_from_input(self, input_data: str, to_address: str | None) -> FlashLoanFeatures:
        selector = input_data[:10] if len(input_data) >= 10 else ""
        has_flash_loan = selector in self.flash_loan_sigs

        provider = ""
        if to_address:
            provider = self.provider_addresses.get(to_address.lower(), "")

        return FlashLoanFeatures(
            has_flash_loan=has_flash_loan,
            flash_loan_count=1 if has_flash_loan else 0,
            flash_loan_providers=[provider] if provider else [],
            flash_loan_amounts=[],
            total_borrowed=0,
            has_callback=False,
            callback_selectors=[],
            nested_flash_loans=False,
            repayment_detected=False,
        )

    def _analyze_call_tree(
        self,
        call: TraceCall,
        flash_loan_calls: list[dict[str, Any]],
        callback_calls: list[str],
        providers: set[str],
        amounts: list[int],
        depth: int,
    ) -> None:
        selector = call.input_data[:10] if len(call.input_data) >= 10 else ""

        if selector in self.flash_loan_sigs:
            flash_loan_calls.append({
                "selector": selector,
                "to": call.to_address,
                "value": call.value,
                "depth": depth,
            })

            if call.to_address.lower() in self.provider_addresses:
                providers.add(self.provider_addresses[call.to_address.lower()])

            amount = self._extract_amount_from_input(call.input_data)
            if amount > 0:
                amounts.append(amount)

        if selector in self.callback_sigs:
            callback_calls.append(selector)

        for child in call.children:
            self._analyze_call_tree(
                child,
                flash_loan_calls,
                callback_calls,
                providers,
                amounts,
                depth + 1,
            )

    def _extract_amount_from_input(self, input_data: str) -> int:
        if len(input_data) < 74:
            return 0

        try:
            amount_hex = input_data[10:74]
            return int(amount_hex, 16)
        except ValueError:
            return 0

    def _detect_nested_flash_loans(self, flash_loan_calls: list[dict[str, Any]]) -> bool:
        if len(flash_loan_calls) <= 1:
            return False

        depths = [c["depth"] for c in flash_loan_calls]
        return len(set(depths)) > 1

    def _detect_repayment(self, trace: TransactionTrace) -> bool:
        transfer_sig = "0xa9059cbb"
        transfer_from_sig = "0x23b872dd"

        if not trace.call_trace:
            return False

        return self._has_transfer_call(trace.call_trace, transfer_sig, transfer_from_sig)

    def _has_transfer_call(self, call: TraceCall, transfer_sig: str, transfer_from_sig: str) -> bool:
        selector = call.input_data[:10] if len(call.input_data) >= 10 else ""
        if selector in (transfer_sig, transfer_from_sig):
            return True

        for child in call.children:
            if self._has_transfer_call(child, transfer_sig, transfer_from_sig):
                return True

        return False

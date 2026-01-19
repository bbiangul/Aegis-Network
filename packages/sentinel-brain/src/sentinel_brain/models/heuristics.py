from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sentinel_brain.data.collectors.mempool_listener import PendingTransaction
from sentinel_brain.features.aggregator import AggregatedFeatures


class FilterResult(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"


SAFE_SELECTORS = {
    "0xa9059cbb",  # transfer(address,uint256)
    "0x23b872dd",  # transferFrom(address,address,uint256)
    "0x095ea7b3",  # approve(address,uint256)
    "0x70a08231",  # balanceOf(address)
    "0x18160ddd",  # totalSupply()
    "0xdd62ed3e",  # allowance(address,address)
    "0x313ce567",  # decimals()
    "0x06fdde03",  # name()
    "0x95d89b41",  # symbol()
    "0x40c10f19",  # mint(address,uint256) - caution, context-dependent
    "0x42842e0e",  # safeTransferFrom(address,address,uint256)
    "0xb88d4fde",  # safeTransferFrom(address,address,uint256,bytes)
    "0x6352211e",  # ownerOf(uint256)
    "0xe985e9c5",  # isApprovedForAll(address,address)
    "0xa22cb465",  # setApprovalForAll(address,bool)
}

SUSPICIOUS_SELECTORS = {
    "0x5cffe9de",  # flashLoan
    "0xab9c4b5d",  # flashLoan (Aave v3)
    "0xc1a8a1f5",  # flash (Uniswap)
    "0x490e6cbc",  # flash (Uniswap v3)
    "0x9c3f1e90",  # flashLoan (dYdX)
    "0x022c0d9f",  # swap (Uniswap V2 pair)
    "0x128acb08",  # swap (Uniswap V3)
    "0x7c025200",  # swap (1inch)
    "0x12aa3caf",  # swap (1inch v5)
    "0xe449022e",  # uniswapV3Swap
    "0x0502b1c5",  # unoswap
    "0xb6f9de95",  # swapExactETHForTokensSupportingFeeOnTransferTokens
    "0x791ac947",  # swapExactTokensForETHSupportingFeeOnTransferTokens
}

WHITELISTED_CONTRACTS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9",  # Aave V2
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",  # Aave V3
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 Router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap Universal Router
    "0xba12222222228d8ba445958a75a0704d566bf2c8",  # Balancer Vault
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff",  # 0x Exchange
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch V5 Router
}


@dataclass
class HeuristicResult:
    result: FilterResult
    confidence: float
    reasons: list[str]
    should_analyze: bool
    risk_indicators: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "should_analyze": self.should_analyze,
            "risk_indicators": self.risk_indicators,
        }


class HeuristicFilter:
    def __init__(
        self,
        safe_selectors: set[str] | None = None,
        suspicious_selectors: set[str] | None = None,
        whitelisted_contracts: set[str] | None = None,
        max_safe_gas: int = 100_000,
        min_suspicious_value: int = 10**18,
    ):
        self.safe_selectors = safe_selectors or SAFE_SELECTORS
        self.suspicious_selectors = suspicious_selectors or SUSPICIOUS_SELECTORS
        self.whitelisted_contracts = {
            addr.lower() for addr in (whitelisted_contracts or WHITELISTED_CONTRACTS)
        }
        self.max_safe_gas = max_safe_gas
        self.min_suspicious_value = min_suspicious_value

    def filter(self, tx: PendingTransaction) -> HeuristicResult:
        reasons: list[str] = []
        risk_indicators: list[str] = []

        if tx.is_simple_transfer:
            return HeuristicResult(
                result=FilterResult.SAFE,
                confidence=0.99,
                reasons=["simple_eth_transfer"],
                should_analyze=False,
                risk_indicators=[],
            )

        if tx.gas < self.max_safe_gas and tx.value == 0:
            reasons.append("low_gas_no_value")

        if tx.to_address and tx.to_address.lower() in self.whitelisted_contracts:
            reasons.append("whitelisted_contract")

        selector = tx.selector
        if selector:
            if selector in self.safe_selectors:
                reasons.append("safe_selector")
            elif selector in self.suspicious_selectors:
                risk_indicators.append("suspicious_selector")

        if tx.is_contract_creation:
            risk_indicators.append("contract_creation")

        if tx.value >= self.min_suspicious_value:
            risk_indicators.append("large_value_transfer")

        if tx.gas > 1_000_000:
            risk_indicators.append("high_gas_limit")

        if len(reasons) >= 2 and not risk_indicators:
            return HeuristicResult(
                result=FilterResult.SAFE,
                confidence=0.9,
                reasons=reasons,
                should_analyze=False,
                risk_indicators=[],
            )

        if len(risk_indicators) >= 2:
            return HeuristicResult(
                result=FilterResult.SUSPICIOUS,
                confidence=0.7,
                reasons=reasons,
                should_analyze=True,
                risk_indicators=risk_indicators,
            )

        return HeuristicResult(
            result=FilterResult.UNKNOWN,
            confidence=0.5,
            reasons=reasons,
            should_analyze=True,
            risk_indicators=risk_indicators,
        )

    def filter_with_features(self, features: AggregatedFeatures) -> HeuristicResult:
        reasons: list[str] = []
        risk_indicators: list[str] = []

        has_flash_loan = features.flash_loan.has_flash_loan
        has_large_changes = features.state_variance.large_value_changes > 3
        has_many_transfers = features.state_variance.total_storage_changes > 10
        has_high_value = features.state_variance.max_value_delta > 10**22  # > 10k ETH equiv

        if has_flash_loan:
            risk_indicators.append("flash_loan_detected")

            if features.flash_loan.nested_flash_loans:
                risk_indicators.append("nested_flash_loans")

            if features.flash_loan.total_borrowed > 10**24:
                risk_indicators.append("large_flash_loan")

            # Flash loan + unusual activity = high risk
            if has_large_changes or has_many_transfers or has_high_value:
                risk_indicators.append("flash_loan_with_complex_activity")

        if features.state_variance.variance_ratio > 0.5:
            risk_indicators.append("high_state_variance")

        if has_large_changes:
            risk_indicators.append("multiple_large_changes")

        if has_high_value:
            risk_indicators.append("extreme_value_movement")

        if features.bytecode.matches_known_exploit:
            risk_indicators.append("matches_known_exploit")
            return HeuristicResult(
                result=FilterResult.SUSPICIOUS,
                confidence=0.95,
                reasons=reasons,
                should_analyze=True,
                risk_indicators=risk_indicators,
            )

        if features.bytecode.jaccard_similarity > 0.7:
            risk_indicators.append("high_bytecode_similarity")

        if features.bytecode.contract_age_blocks < 100:
            risk_indicators.append("new_contract")

        if features.bytecode.has_selfdestruct:
            risk_indicators.append("selfdestruct_opcode")

        if features.opcode.delegatecall_count > 0:
            risk_indicators.append("uses_delegatecall")

        if features.opcode.create2_count > 0:
            risk_indicators.append("uses_create2")

        if features.opcode.call_depth > 10:
            risk_indicators.append("deep_call_stack")

        if features.opcode.total_calls > 50:
            risk_indicators.append("high_call_count")

        if len(risk_indicators) == 0:
            return HeuristicResult(
                result=FilterResult.SAFE,
                confidence=0.8,
                reasons=["no_risk_indicators"],
                should_analyze=False,
                risk_indicators=[],
            )

        if len(risk_indicators) >= 3:
            return HeuristicResult(
                result=FilterResult.SUSPICIOUS,
                confidence=min(0.5 + len(risk_indicators) * 0.1, 0.95),
                reasons=reasons,
                should_analyze=True,
                risk_indicators=risk_indicators,
            )

        return HeuristicResult(
            result=FilterResult.UNKNOWN,
            confidence=0.5,
            reasons=reasons,
            should_analyze=True,
            risk_indicators=risk_indicators,
        )

    def quick_filter(self, tx: PendingTransaction) -> bool:
        if tx.is_simple_transfer:
            return False

        if tx.gas < self.max_safe_gas:
            return False

        if tx.to_address and tx.to_address.lower() in self.whitelisted_contracts:
            selector = tx.selector
            if selector and selector in self.safe_selectors:
                return False

        return True

    def add_whitelisted_contract(self, address: str) -> None:
        self.whitelisted_contracts.add(address.lower())

    def add_safe_selector(self, selector: str) -> None:
        self.safe_selectors.add(selector)

    def add_suspicious_selector(self, selector: str) -> None:
        self.suspicious_selectors.add(selector)

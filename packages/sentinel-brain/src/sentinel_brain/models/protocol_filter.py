"""
Protocol-aware filtering to reduce false positives.

Known DeFi protocols have inherently complex transactions that look
suspicious to generic anomaly detection. This module provides:

1. Protocol identification (which protocol is being used)
2. Operation classification (swap, deposit, borrow, etc.)
3. Sanity bounds (is this within normal parameters for this operation)
4. Risk adjustment (lower risk for known-safe patterns)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sentinel_brain.features.aggregator import AggregatedFeatures


class Protocol(Enum):
    """Known DeFi protocols."""
    UNKNOWN = "unknown"

    # DEXes
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    SUSHISWAP = "sushiswap"
    CURVE = "curve"
    BALANCER = "balancer"

    # Lending
    AAVE_V2 = "aave_v2"
    AAVE_V3 = "aave_v3"
    COMPOUND = "compound"
    MAKER = "maker"

    # Aggregators
    ONE_INCH = "1inch"
    PARASWAP = "paraswap"
    COWSWAP = "cowswap"

    # Bridges
    STARGATE = "stargate"
    HOP = "hop"
    ACROSS = "across"

    # Yield
    YEARN = "yearn"
    CONVEX = "convex"
    LIDO = "lido"


class OperationType(Enum):
    """Types of DeFi operations."""
    UNKNOWN = "unknown"

    # DEX operations
    SWAP = "swap"
    ADD_LIQUIDITY = "add_liquidity"
    REMOVE_LIQUIDITY = "remove_liquidity"

    # Lending operations
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    BORROW = "borrow"
    REPAY = "repay"
    LIQUIDATE = "liquidate"

    # Flash loans (legitimate uses)
    FLASH_LOAN_ARBITRAGE = "flash_loan_arbitrage"
    FLASH_LOAN_COLLATERAL_SWAP = "flash_loan_collateral_swap"

    # Other
    STAKE = "stake"
    UNSTAKE = "unstake"
    CLAIM_REWARDS = "claim_rewards"
    GOVERNANCE = "governance"
    BRIDGE = "bridge"


# Protocol contract addresses (Ethereum mainnet)
PROTOCOL_ADDRESSES = {
    # Uniswap
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": Protocol.UNISWAP_V2,  # Router
    "0xe592427a0aece92de3edee1f18e0157c05861564": Protocol.UNISWAP_V3,  # Router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": Protocol.UNISWAP_V3,  # Router 2
    "0x000000000022d473030f116ddee9f6b43ac78ba3": Protocol.UNISWAP_V3,  # Permit2
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": Protocol.UNISWAP_V3,  # Universal Router

    # Sushiswap
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": Protocol.SUSHISWAP,

    # Curve
    "0x99a58482bd75cbab83b27ec03ca68ff489b5788f": Protocol.CURVE,  # Router

    # Balancer
    "0xba12222222228d8ba445958a75a0704d566bf2c8": Protocol.BALANCER,  # Vault

    # Aave
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9": Protocol.AAVE_V2,  # Lending Pool
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": Protocol.AAVE_V3,  # Pool

    # Compound
    "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b": Protocol.COMPOUND,  # Comptroller

    # 1inch
    "0x1111111254eeb25477b68fb85ed929f73a960582": Protocol.ONE_INCH,  # V5
    "0x111111125421ca6dc452d289314280a0f8842a65": Protocol.ONE_INCH,  # V6

    # Lido
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": Protocol.LIDO,  # stETH

    # Maker
    "0x5ef30b9986345249bc32d8928b7ee64de9435e39": Protocol.MAKER,  # CDP Manager
}

# Function selectors for operation classification
OPERATION_SELECTORS = {
    # Swaps
    "0x38ed1739": OperationType.SWAP,  # swapExactTokensForTokens
    "0x8803dbee": OperationType.SWAP,  # swapTokensForExactTokens
    "0x7ff36ab5": OperationType.SWAP,  # swapExactETHForTokens
    "0x18cbafe5": OperationType.SWAP,  # swapExactTokensForETH
    "0x5c11d795": OperationType.SWAP,  # swapExactTokensForTokensSupportingFeeOnTransferTokens
    "0xb6f9de95": OperationType.SWAP,  # swapExactETHForTokensSupportingFeeOnTransferTokens
    "0x791ac947": OperationType.SWAP,  # swapExactTokensForETHSupportingFeeOnTransferTokens
    "0x04e45aaf": OperationType.SWAP,  # exactInputSingle (V3)
    "0xc04b8d59": OperationType.SWAP,  # exactInput (V3)
    "0x472b43f3": OperationType.SWAP,  # swapExactTokensForTokens (Universal Router)
    "0x3593564c": OperationType.SWAP,  # execute (Universal Router)
    "0x12aa3caf": OperationType.SWAP,  # swap (1inch)
    "0xe449022e": OperationType.SWAP,  # uniswapV3Swap (1inch)

    # Liquidity
    "0xe8e33700": OperationType.ADD_LIQUIDITY,  # addLiquidity
    "0xf305d719": OperationType.ADD_LIQUIDITY,  # addLiquidityETH
    "0xbaa2abde": OperationType.REMOVE_LIQUIDITY,  # removeLiquidity
    "0x02751cec": OperationType.REMOVE_LIQUIDITY,  # removeLiquidityETH

    # Aave
    "0xe8eda9df": OperationType.DEPOSIT,  # deposit (V2)
    "0x617ba037": OperationType.DEPOSIT,  # supply (V3)
    "0x69328dec": OperationType.WITHDRAW,  # withdraw
    "0xa415bcad": OperationType.BORROW,  # borrow
    "0x573ade81": OperationType.REPAY,  # repay
    "0x00a718a9": OperationType.LIQUIDATE,  # liquidationCall

    # Compound
    "0xa0712d68": OperationType.DEPOSIT,  # mint
    "0xdb006a75": OperationType.WITHDRAW,  # redeem
    "0xc5ebeaec": OperationType.BORROW,  # borrow
    "0x0e752702": OperationType.REPAY,  # repayBorrow

    # Staking
    "0xa694fc3a": OperationType.STAKE,  # stake
    "0x2e1a7d4d": OperationType.UNSTAKE,  # withdraw (unstake)
    "0x3d18b912": OperationType.CLAIM_REWARDS,  # getReward
    "0xe9fad8ee": OperationType.UNSTAKE,  # exit

    # Governance
    "0x15373e3d": OperationType.GOVERNANCE,  # castVote
    "0x56781388": OperationType.GOVERNANCE,  # castVote
}

# Normal bounds for operations (to detect anomalies within known protocols)
OPERATION_BOUNDS = {
    OperationType.SWAP: {
        "max_value_usd": 10_000_000,  # $10M max for single swap
        "max_price_impact_bps": 500,  # 5% max price impact
        "max_gas": 1_000_000,
        "max_contracts": 15,
    },
    OperationType.ADD_LIQUIDITY: {
        "max_value_usd": 50_000_000,
        "max_gas": 500_000,
        "max_contracts": 10,
    },
    OperationType.DEPOSIT: {
        "max_value_usd": 100_000_000,
        "max_gas": 500_000,
        "max_contracts": 10,
    },
    OperationType.BORROW: {
        "max_value_usd": 50_000_000,
        "min_health_factor": 1.1,
        "max_gas": 800_000,
        "max_contracts": 15,
    },
    OperationType.FLASH_LOAN_ARBITRAGE: {
        "max_profit_usd": 100_000,  # Legitimate arb is usually small
        "max_gas": 2_000_000,
        "must_repay": True,
    },
}


@dataclass
class ProtocolContext:
    """Context about the protocol and operation."""
    protocol: Protocol
    operation: OperationType
    is_known_protocol: bool
    is_known_operation: bool
    within_bounds: bool
    bound_violations: list[str]
    risk_adjustment: float  # -1.0 to 1.0, negative reduces risk


@dataclass
class FilterResult:
    """Result of protocol filtering."""
    context: ProtocolContext
    adjusted_risk_score: float
    original_risk_score: float
    explanation: str
    should_alert: bool


class ProtocolFilter:
    """
    Filter that adjusts risk based on protocol context.

    Known protocols with normal operations get reduced risk scores.
    Unknown protocols or abnormal operations get increased scrutiny.
    """

    def __init__(
        self,
        protocol_addresses: dict[str, Protocol] | None = None,
        operation_selectors: dict[str, OperationType] | None = None,
        enable_bounds_check: bool = True,
    ):
        self.protocol_addresses = {
            k.lower(): v for k, v in (protocol_addresses or PROTOCOL_ADDRESSES).items()
        }
        self.operation_selectors = operation_selectors or OPERATION_SELECTORS
        self.enable_bounds_check = enable_bounds_check

    def identify_protocol(self, to_address: str | None) -> Protocol:
        """Identify which protocol a transaction interacts with."""
        if not to_address:
            return Protocol.UNKNOWN
        return self.protocol_addresses.get(to_address.lower(), Protocol.UNKNOWN)

    def identify_operation(self, input_data: str) -> OperationType:
        """Identify the operation type from function selector."""
        if len(input_data) < 10:
            return OperationType.UNKNOWN
        selector = input_data[:10].lower()
        return self.operation_selectors.get(selector, OperationType.UNKNOWN)

    def check_bounds(
        self,
        operation: OperationType,
        features: AggregatedFeatures,
    ) -> tuple[bool, list[str]]:
        """Check if operation is within normal bounds."""
        if not self.enable_bounds_check:
            return True, []

        bounds = OPERATION_BOUNDS.get(operation)
        if not bounds:
            return True, []

        violations = []

        # Check gas
        max_gas = bounds.get("max_gas")
        if max_gas and features.metadata.get("gas_used", 0) > max_gas:
            violations.append(f"gas_exceeds_{max_gas}")

        # Check contract count
        max_contracts = bounds.get("max_contracts")
        if max_contracts and features.state_variance.unique_contracts_modified > max_contracts:
            violations.append(f"contracts_exceed_{max_contracts}")

        # Check value (rough estimate from features)
        max_value = bounds.get("max_value_usd")
        if max_value:
            # Rough ETH price estimate for bounds checking
            eth_price = 2000
            value_usd = features.state_variance.max_value_delta / 1e18 * eth_price
            if value_usd > max_value:
                violations.append(f"value_exceeds_${max_value:,.0f}")

        return len(violations) == 0, violations

    def get_context(
        self,
        features: AggregatedFeatures,
        to_address: str | None = None,
        input_data: str = "",
    ) -> ProtocolContext:
        """Get full protocol context for a transaction."""
        protocol = self.identify_protocol(to_address)
        operation = self.identify_operation(input_data)

        is_known_protocol = protocol != Protocol.UNKNOWN
        is_known_operation = operation != OperationType.UNKNOWN

        within_bounds, violations = self.check_bounds(operation, features)

        # Calculate risk adjustment
        risk_adjustment = self._calculate_risk_adjustment(
            protocol, operation, is_known_protocol, is_known_operation,
            within_bounds, features
        )

        return ProtocolContext(
            protocol=protocol,
            operation=operation,
            is_known_protocol=is_known_protocol,
            is_known_operation=is_known_operation,
            within_bounds=within_bounds,
            bound_violations=violations,
            risk_adjustment=risk_adjustment,
        )

    def _calculate_risk_adjustment(
        self,
        protocol: Protocol,
        operation: OperationType,
        is_known_protocol: bool,
        is_known_operation: bool,
        within_bounds: bool,
        features: AggregatedFeatures,
    ) -> float:
        """
        Calculate risk adjustment factor.

        Returns:
            -1.0 to 1.0 where:
            - Negative values reduce risk (trusted protocol/operation)
            - Positive values increase risk (suspicious patterns)
            - 0.0 means no adjustment
        """
        adjustment = 0.0

        # CRITICAL: Only reduce risk if BOTH protocol AND operation are known
        # This prevents unknown transactions from getting unearned risk reduction
        if is_known_protocol and is_known_operation:
            # Known protocol + operation gets combined reduction
            adjustment -= 0.20

            # Within bounds gets additional reduction (only if we can verify bounds)
            if within_bounds:
                adjustment -= 0.10
            else:
                # Bound violations increase risk significantly
                adjustment += 0.25
        elif not is_known_protocol and not is_known_operation:
            # Completely unknown: no adjustment (neutral)
            pass
        else:
            # Partial knowledge: minimal reduction
            if is_known_protocol:
                adjustment -= 0.05
            if is_known_operation:
                adjustment -= 0.05

        # Flash loan in non-flash-loan operation ALWAYS increases risk
        if features.flash_loan.has_flash_loan:
            if operation not in [
                OperationType.FLASH_LOAN_ARBITRAGE,
                OperationType.FLASH_LOAN_COLLATERAL_SWAP,
                OperationType.LIQUIDATE,
            ]:
                adjustment += 0.35  # Increased from 0.30

        # Specific safe operations get extra reduction ONLY if fully verified
        safe_operations = {
            OperationType.SWAP,
            OperationType.ADD_LIQUIDITY,
            OperationType.DEPOSIT,
            OperationType.STAKE,
            OperationType.CLAIM_REWARDS,
            OperationType.GOVERNANCE,
        }
        if (is_known_protocol and operation in safe_operations and
            within_bounds and not features.flash_loan.has_flash_loan):
            adjustment -= 0.10

        return max(-0.5, min(0.5, adjustment))

    def filter(
        self,
        features: AggregatedFeatures,
        original_risk_score: float,
        to_address: str | None = None,
        input_data: str = "",
    ) -> FilterResult:
        """
        Apply protocol filter to adjust risk score.

        Args:
            features: Extracted features
            original_risk_score: Risk score from ML/heuristics
            to_address: Transaction destination
            input_data: Transaction input data

        Returns:
            FilterResult with adjusted risk score
        """
        context = self.get_context(features, to_address, input_data)

        # Apply adjustment
        adjusted_score = original_risk_score + (context.risk_adjustment * original_risk_score)
        adjusted_score = max(0.0, min(1.0, adjusted_score))

        # Generate explanation
        explanation = self._generate_explanation(context, original_risk_score, adjusted_score)

        # Determine if should alert (using adjusted score)
        should_alert = adjusted_score >= 0.5

        return FilterResult(
            context=context,
            adjusted_risk_score=adjusted_score,
            original_risk_score=original_risk_score,
            explanation=explanation,
            should_alert=should_alert,
        )

    def _generate_explanation(
        self,
        context: ProtocolContext,
        original: float,
        adjusted: float,
    ) -> str:
        """Generate human-readable explanation of filtering."""
        parts = []

        if context.is_known_protocol:
            parts.append(f"Known protocol: {context.protocol.value}")
        else:
            parts.append("Unknown protocol")

        if context.is_known_operation:
            parts.append(f"Operation: {context.operation.value}")

        if not context.within_bounds:
            parts.append(f"Bound violations: {', '.join(context.bound_violations)}")

        if abs(adjusted - original) > 0.01:
            direction = "reduced" if adjusted < original else "increased"
            parts.append(f"Risk {direction} by {abs(adjusted - original):.1%}")

        return ". ".join(parts)

    def add_protocol(self, address: str, protocol: Protocol) -> None:
        """Add a protocol address to the whitelist."""
        self.protocol_addresses[address.lower()] = protocol

    def add_operation(self, selector: str, operation: OperationType) -> None:
        """Add an operation selector mapping."""
        self.operation_selectors[selector.lower()] = operation

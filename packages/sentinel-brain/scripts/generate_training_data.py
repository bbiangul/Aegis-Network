#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
import sys

import numpy as np
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sentinel_brain.data.exploits import ExploitRegistry, AttackVector, Detectability
from sentinel_brain.features.extractors.flash_loan import FlashLoanFeatures
from sentinel_brain.features.extractors.state_variance import StateVarianceFeatures
from sentinel_brain.features.extractors.bytecode import BytecodeFeatures
from sentinel_brain.features.extractors.opcode import OpcodeFeatures
from sentinel_brain.features.aggregator import AggregatedFeatures

logger = structlog.get_logger()


def generate_benign_features() -> AggregatedFeatures:
    is_simple_transfer = random.random() < 0.4
    is_swap = random.random() < 0.3
    is_lending = random.random() < 0.2

    if is_simple_transfer:
        return _simple_transfer_features()
    elif is_swap:
        return _swap_features()
    elif is_lending:
        return _lending_features()
    else:
        return _random_contract_interaction()


def _simple_transfer_features() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(1, 3),
            unique_contracts_modified=1,
            unique_slots_modified=random.randint(1, 2),
            balance_slot_changes=1,
            large_value_changes=0,
            max_value_delta=random.randint(1000, 100000),
            avg_value_delta=random.randint(1000, 50000),
            variance_ratio=random.uniform(0.0, 0.1),
            zero_to_nonzero=0,
            nonzero_to_zero=0,
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=0, bytecode_hash="", is_contract=False, is_proxy=False,
            proxy_type=None, contract_age_blocks=0, is_verified=False,
            matches_known_exploit=False, matched_exploit_id=None,
            jaccard_similarity=0.0, has_selfdestruct=False, has_delegatecall=False,
            has_create2=False, unique_opcodes=0,
        ),
        opcode=OpcodeFeatures(
            total_calls=1, call_depth=1, delegatecall_count=0, staticcall_count=0,
            create_count=0, create2_count=0, selfdestruct_count=0, call_count=1,
            internal_calls=0, external_calls=1, unique_call_types=1,
            call_value_transfers=1, gas_forwarded_ratio=0.0, revert_count=0,
        ),
        metadata={"type": "simple_transfer", "label": 0},
    )


def _swap_features() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(4, 12),
            unique_contracts_modified=random.randint(2, 4),
            unique_slots_modified=random.randint(4, 10),
            balance_slot_changes=random.randint(2, 4),
            large_value_changes=random.randint(0, 1),
            max_value_delta=random.randint(10000, 1000000),
            avg_value_delta=random.randint(5000, 500000),
            variance_ratio=random.uniform(0.05, 0.2),
            zero_to_nonzero=random.randint(0, 1),
            nonzero_to_zero=random.randint(0, 1),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(5000, 20000), bytecode_hash="0xabc123",
            is_contract=True, is_proxy=random.random() < 0.3,
            proxy_type="eip1967" if random.random() < 0.3 else None,
            contract_age_blocks=random.randint(100000, 5000000), is_verified=True,
            matches_known_exploit=False, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.0, 0.1), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.3, has_create2=False,
            unique_opcodes=random.randint(40, 80),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(3, 10), call_depth=random.randint(2, 4),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(1, 3),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(2, 6), internal_calls=random.randint(1, 4),
            external_calls=random.randint(2, 5), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(0, 2),
            gas_forwarded_ratio=random.uniform(0.6, 0.95), revert_count=0,
        ),
        metadata={"type": "swap", "label": 0},
    )


def _lending_features() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(5, 15),
            unique_contracts_modified=random.randint(2, 5),
            unique_slots_modified=random.randint(5, 12),
            balance_slot_changes=random.randint(2, 5),
            large_value_changes=random.randint(0, 2),
            max_value_delta=random.randint(100000, 10000000),
            avg_value_delta=random.randint(50000, 5000000),
            variance_ratio=random.uniform(0.1, 0.3),
            zero_to_nonzero=random.randint(0, 2),
            nonzero_to_zero=random.randint(0, 2),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(10000, 30000), bytecode_hash="0xdef456",
            is_contract=True, is_proxy=random.random() < 0.5,
            proxy_type="transparent" if random.random() < 0.5 else None,
            contract_age_blocks=random.randint(500000, 8000000), is_verified=True,
            matches_known_exploit=False, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.0, 0.15), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.5, has_create2=False,
            unique_opcodes=random.randint(50, 100),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(5, 15), call_depth=random.randint(2, 5),
            delegatecall_count=random.randint(0, 3), staticcall_count=random.randint(2, 5),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(3, 8), internal_calls=random.randint(2, 6),
            external_calls=random.randint(3, 8), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(0, 1),
            gas_forwarded_ratio=random.uniform(0.7, 0.95), revert_count=0,
        ),
        metadata={"type": "lending", "label": 0},
    )


def _random_contract_interaction() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(1, 8),
            unique_contracts_modified=random.randint(1, 3),
            unique_slots_modified=random.randint(1, 6),
            balance_slot_changes=random.randint(0, 2),
            large_value_changes=random.randint(0, 1),
            max_value_delta=random.randint(1000, 500000),
            avg_value_delta=random.randint(500, 250000),
            variance_ratio=random.uniform(0.0, 0.15),
            zero_to_nonzero=random.randint(0, 1),
            nonzero_to_zero=random.randint(0, 1),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(1000, 15000), bytecode_hash="0x789abc",
            is_contract=True, is_proxy=random.random() < 0.2,
            proxy_type=None, contract_age_blocks=random.randint(10000, 3000000),
            is_verified=random.random() < 0.7, matches_known_exploit=False,
            matched_exploit_id=None, jaccard_similarity=random.uniform(0.0, 0.1),
            has_selfdestruct=False, has_delegatecall=random.random() < 0.2,
            has_create2=False, unique_opcodes=random.randint(30, 70),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(1, 8), call_depth=random.randint(1, 3),
            delegatecall_count=random.randint(0, 1), staticcall_count=random.randint(0, 2),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(1, 5), internal_calls=random.randint(0, 3),
            external_calls=random.randint(1, 4), unique_call_types=random.randint(1, 3),
            call_value_transfers=random.randint(0, 1),
            gas_forwarded_ratio=random.uniform(0.5, 0.9), revert_count=0,
        ),
        metadata={"type": "contract_interaction", "label": 0},
    )


def generate_exploit_features(attack_vector: AttackVector) -> AggregatedFeatures:
    if attack_vector == AttackVector.FLASH_LOAN:
        return _flash_loan_exploit()
    elif attack_vector == AttackVector.ORACLE_MANIPULATION:
        return _oracle_manipulation_exploit()
    elif attack_vector == AttackVector.REENTRANCY:
        return _reentrancy_exploit()
    elif attack_vector == AttackVector.LOGIC_ERROR:
        return _logic_error_exploit()
    elif attack_vector == AttackVector.GOVERNANCE_ATTACK:
        return _governance_exploit()
    elif attack_vector == AttackVector.ARITHMETIC_OVERFLOW:
        return _arithmetic_overflow_exploit()
    elif attack_vector == AttackVector.DONATION_ATTACK:
        return _donation_attack_exploit()
    elif attack_vector == AttackVector.APPROVAL_EXPLOIT:
        return _approval_exploit()
    elif attack_vector == AttackVector.ROUNDING_ERROR:
        return _rounding_error_exploit()
    elif attack_vector == AttackVector.MINT_VULNERABILITY:
        return _mint_vulnerability_exploit()
    elif attack_vector == AttackVector.COMPILER_BUG:
        return _compiler_bug_exploit()
    else:
        return _generic_exploit()


def _flash_loan_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=True, flash_loan_count=random.randint(1, 3),
            flash_loan_providers=random.sample(["aave_v2", "aave_v3", "balancer", "dydx"], random.randint(1, 2)),
            flash_loan_amounts=[random.randint(1000000, 100000000) for _ in range(random.randint(1, 3))],
            total_borrowed=random.randint(10000000, 500000000), has_callback=True,
            callback_selectors=["executeOperation"], nested_flash_loans=random.random() < 0.3,
            repayment_detected=True,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(20, 100),
            unique_contracts_modified=random.randint(5, 15),
            unique_slots_modified=random.randint(15, 50),
            balance_slot_changes=random.randint(5, 15),
            large_value_changes=random.randint(3, 10),
            max_value_delta=random.randint(10000000, 500000000),
            avg_value_delta=random.randint(5000000, 100000000),
            variance_ratio=random.uniform(0.4, 0.9),
            zero_to_nonzero=random.randint(2, 8),
            nonzero_to_zero=random.randint(2, 8),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(2000, 8000), bytecode_hash="0xexploit1",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 100), is_verified=False,
            matches_known_exploit=random.random() < 0.3, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.2, 0.5), has_selfdestruct=random.random() < 0.2,
            has_delegatecall=random.random() < 0.4, has_create2=random.random() < 0.3,
            unique_opcodes=random.randint(50, 90),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(20, 80), call_depth=random.randint(5, 15),
            delegatecall_count=random.randint(0, 5), staticcall_count=random.randint(5, 15),
            create_count=random.randint(0, 2), create2_count=random.randint(0, 2),
            selfdestruct_count=random.randint(0, 1), call_count=random.randint(15, 50),
            internal_calls=random.randint(10, 30), external_calls=random.randint(10, 40),
            unique_call_types=random.randint(4, 6), call_value_transfers=random.randint(3, 10),
            gas_forwarded_ratio=random.uniform(0.8, 0.99), revert_count=random.randint(0, 3),
        ),
        metadata={"type": "flash_loan_exploit", "label": 1},
    )


def _oracle_manipulation_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.7, flash_loan_count=random.randint(0, 2),
            flash_loan_providers=["aave_v2"] if random.random() < 0.7 else [],
            flash_loan_amounts=[random.randint(5000000, 50000000)] if random.random() < 0.7 else [],
            total_borrowed=random.randint(0, 100000000), has_callback=random.random() < 0.7,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=random.random() < 0.7,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(15, 60),
            unique_contracts_modified=random.randint(4, 10),
            unique_slots_modified=random.randint(10, 35),
            balance_slot_changes=random.randint(4, 12),
            large_value_changes=random.randint(4, 15),
            max_value_delta=random.randint(50000000, 300000000),
            avg_value_delta=random.randint(10000000, 100000000),
            variance_ratio=random.uniform(0.5, 0.95),
            zero_to_nonzero=random.randint(1, 5),
            nonzero_to_zero=random.randint(1, 5),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(3000, 10000), bytecode_hash="0xexploit2",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 50), is_verified=False,
            matches_known_exploit=random.random() < 0.2, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.15, 0.4), has_selfdestruct=random.random() < 0.15,
            has_delegatecall=random.random() < 0.3, has_create2=random.random() < 0.2,
            unique_opcodes=random.randint(45, 85),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(15, 50), call_depth=random.randint(4, 10),
            delegatecall_count=random.randint(0, 3), staticcall_count=random.randint(8, 20),
            create_count=random.randint(0, 1), create2_count=random.randint(0, 1),
            selfdestruct_count=0, call_count=random.randint(10, 35),
            internal_calls=random.randint(5, 20), external_calls=random.randint(8, 25),
            unique_call_types=random.randint(3, 5), call_value_transfers=random.randint(2, 8),
            gas_forwarded_ratio=random.uniform(0.75, 0.95), revert_count=random.randint(0, 2),
        ),
        metadata={"type": "oracle_manipulation", "label": 1},
    )


def _reentrancy_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.4, flash_loan_count=random.randint(0, 1),
            flash_loan_providers=["aave_v2"] if random.random() < 0.4 else [],
            flash_loan_amounts=[], total_borrowed=random.randint(0, 50000000),
            has_callback=True, callback_selectors=["fallback", "receive"],
            nested_flash_loans=False, repayment_detected=random.random() < 0.4,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(30, 150),
            unique_contracts_modified=random.randint(2, 6),
            unique_slots_modified=random.randint(5, 20),
            balance_slot_changes=random.randint(10, 50),
            large_value_changes=random.randint(5, 20),
            max_value_delta=random.randint(10000000, 200000000),
            avg_value_delta=random.randint(1000000, 50000000),
            variance_ratio=random.uniform(0.3, 0.8),
            zero_to_nonzero=random.randint(0, 3),
            nonzero_to_zero=random.randint(5, 20),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(1500, 5000), bytecode_hash="0xexploit3",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 20), is_verified=False,
            matches_known_exploit=random.random() < 0.25, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.2, 0.45), has_selfdestruct=random.random() < 0.1,
            has_delegatecall=random.random() < 0.2, has_create2=random.random() < 0.1,
            unique_opcodes=random.randint(35, 70),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(30, 200), call_depth=random.randint(8, 30),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(2, 8),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(25, 150), internal_calls=random.randint(20, 100),
            external_calls=random.randint(5, 30), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(10, 50),
            gas_forwarded_ratio=random.uniform(0.85, 0.99), revert_count=random.randint(0, 5),
        ),
        metadata={"type": "reentrancy", "label": 1},
    )


def _logic_error_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.3, flash_loan_count=random.randint(0, 1),
            flash_loan_providers=[], flash_loan_amounts=[], total_borrowed=0,
            has_callback=False, callback_selectors=[], nested_flash_loans=False,
            repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(10, 40),
            unique_contracts_modified=random.randint(2, 6),
            unique_slots_modified=random.randint(8, 25),
            balance_slot_changes=random.randint(3, 10),
            large_value_changes=random.randint(2, 8),
            max_value_delta=random.randint(20000000, 300000000),
            avg_value_delta=random.randint(5000000, 80000000),
            variance_ratio=random.uniform(0.35, 0.75),
            zero_to_nonzero=random.randint(1, 5),
            nonzero_to_zero=random.randint(1, 5),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(5000, 20000), bytecode_hash="0xexploit4",
            is_contract=True, is_proxy=random.random() < 0.3, proxy_type=None,
            contract_age_blocks=random.randint(100, 1000), is_verified=random.random() < 0.5,
            matches_known_exploit=random.random() < 0.15, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.1, 0.3), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.4, has_create2=random.random() < 0.15,
            unique_opcodes=random.randint(50, 90),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(10, 40), call_depth=random.randint(3, 8),
            delegatecall_count=random.randint(0, 4), staticcall_count=random.randint(3, 10),
            create_count=random.randint(0, 1), create2_count=0, selfdestruct_count=0,
            call_count=random.randint(8, 30), internal_calls=random.randint(5, 20),
            external_calls=random.randint(5, 20), unique_call_types=random.randint(3, 5),
            call_value_transfers=random.randint(1, 5),
            gas_forwarded_ratio=random.uniform(0.7, 0.9), revert_count=random.randint(0, 2),
        ),
        metadata={"type": "logic_error", "label": 1},
    )


def _governance_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=True, flash_loan_count=random.randint(1, 2),
            flash_loan_providers=["aave_v2", "aave_v3"],
            flash_loan_amounts=[random.randint(50000000, 200000000)],
            total_borrowed=random.randint(50000000, 300000000), has_callback=True,
            callback_selectors=["executeOperation"], nested_flash_loans=False,
            repayment_detected=True,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(25, 80),
            unique_contracts_modified=random.randint(5, 12),
            unique_slots_modified=random.randint(15, 45),
            balance_slot_changes=random.randint(5, 15),
            large_value_changes=random.randint(3, 12),
            max_value_delta=random.randint(50000000, 400000000),
            avg_value_delta=random.randint(20000000, 150000000),
            variance_ratio=random.uniform(0.45, 0.85),
            zero_to_nonzero=random.randint(2, 8),
            nonzero_to_zero=random.randint(2, 8),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(3000, 12000), bytecode_hash="0xexploit5",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 50), is_verified=False,
            matches_known_exploit=random.random() < 0.2, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.15, 0.35), has_selfdestruct=random.random() < 0.1,
            has_delegatecall=random.random() < 0.3, has_create2=random.random() < 0.2,
            unique_opcodes=random.randint(55, 95),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(20, 60), call_depth=random.randint(5, 12),
            delegatecall_count=random.randint(0, 4), staticcall_count=random.randint(5, 15),
            create_count=random.randint(0, 1), create2_count=random.randint(0, 1),
            selfdestruct_count=0, call_count=random.randint(15, 45),
            internal_calls=random.randint(10, 30), external_calls=random.randint(10, 30),
            unique_call_types=random.randint(4, 6), call_value_transfers=random.randint(2, 8),
            gas_forwarded_ratio=random.uniform(0.8, 0.95), revert_count=random.randint(0, 2),
        ),
        metadata={"type": "governance_attack", "label": 1},
    )


def _arithmetic_overflow_exploit() -> AggregatedFeatures:
    """Cetus Protocol 2025 style - arithmetic overflow in checked operations."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.3, flash_loan_count=random.randint(0, 1),
            flash_loan_providers=[], flash_loan_amounts=[], total_borrowed=0,
            has_callback=False, callback_selectors=[], nested_flash_loans=False,
            repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(8, 30),
            unique_contracts_modified=random.randint(2, 5),
            unique_slots_modified=random.randint(5, 20),
            balance_slot_changes=random.randint(2, 8),
            large_value_changes=random.randint(3, 15),
            max_value_delta=random.randint(100000000, 999999999),
            avg_value_delta=random.randint(50000000, 500000000),
            variance_ratio=random.uniform(0.6, 0.95),
            zero_to_nonzero=random.randint(1, 4),
            nonzero_to_zero=random.randint(1, 4),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(3000, 12000), bytecode_hash="0xoverflow",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(50, 500), is_verified=random.random() < 0.6,
            matches_known_exploit=random.random() < 0.2, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.15, 0.35), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.2, has_create2=False,
            unique_opcodes=random.randint(50, 85),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(8, 25), call_depth=random.randint(2, 6),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(3, 10),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(6, 20), internal_calls=random.randint(4, 15),
            external_calls=random.randint(4, 12), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(1, 5),
            gas_forwarded_ratio=random.uniform(0.6, 0.85), revert_count=random.randint(0, 1),
        ),
        metadata={"type": "arithmetic_overflow", "label": 1},
    )


def _donation_attack_exploit() -> AggregatedFeatures:
    """Sonne Finance 2024, Hundred Finance 2023 style - donation/inflation attack."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=True, flash_loan_count=random.randint(1, 2),
            flash_loan_providers=random.sample(["aave_v2", "aave_v3", "balancer"], 1),
            flash_loan_amounts=[random.randint(1000000, 50000000)],
            total_borrowed=random.randint(5000000, 100000000), has_callback=True,
            callback_selectors=["executeOperation"], nested_flash_loans=False,
            repayment_detected=True,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(12, 45),
            unique_contracts_modified=random.randint(3, 8),
            unique_slots_modified=random.randint(8, 30),
            balance_slot_changes=random.randint(4, 12),
            large_value_changes=random.randint(3, 10),
            max_value_delta=random.randint(20000000, 200000000),
            avg_value_delta=random.randint(10000000, 80000000),
            variance_ratio=random.uniform(0.45, 0.85),
            zero_to_nonzero=random.randint(2, 6),
            nonzero_to_zero=random.randint(1, 4),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(2500, 8000), bytecode_hash="0xdonation",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 100), is_verified=False,
            matches_known_exploit=random.random() < 0.25, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.2, 0.45), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.3, has_create2=random.random() < 0.2,
            unique_opcodes=random.randint(45, 80),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(15, 50), call_depth=random.randint(4, 10),
            delegatecall_count=random.randint(0, 3), staticcall_count=random.randint(4, 12),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(12, 40), internal_calls=random.randint(8, 25),
            external_calls=random.randint(8, 25), unique_call_types=random.randint(3, 5),
            call_value_transfers=random.randint(3, 10),
            gas_forwarded_ratio=random.uniform(0.75, 0.95), revert_count=random.randint(0, 2),
        ),
        metadata={"type": "donation_attack", "label": 1},
    )


def _approval_exploit() -> AggregatedFeatures:
    """Li.Fi 2024, BadgerDAO 2021 style - token approval exploitation."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(20, 80),
            unique_contracts_modified=random.randint(5, 15),
            unique_slots_modified=random.randint(15, 50),
            balance_slot_changes=random.randint(8, 25),
            large_value_changes=random.randint(5, 20),
            max_value_delta=random.randint(5000000, 150000000),
            avg_value_delta=random.randint(2000000, 50000000),
            variance_ratio=random.uniform(0.35, 0.75),
            zero_to_nonzero=random.randint(0, 3),
            nonzero_to_zero=random.randint(5, 20),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(1500, 6000), bytecode_hash="0xapproval",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 50), is_verified=False,
            matches_known_exploit=random.random() < 0.2, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.15, 0.4), has_selfdestruct=random.random() < 0.1,
            has_delegatecall=random.random() < 0.4, has_create2=False,
            unique_opcodes=random.randint(35, 65),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(25, 100), call_depth=random.randint(3, 8),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(5, 15),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(20, 80), internal_calls=random.randint(5, 20),
            external_calls=random.randint(15, 60), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(5, 25),
            gas_forwarded_ratio=random.uniform(0.7, 0.9), revert_count=random.randint(0, 5),
        ),
        metadata={"type": "approval_exploit", "label": 1},
    )


def _rounding_error_exploit() -> AggregatedFeatures:
    """Abracadabra 2025 style - rounding/precision error exploitation."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.4, flash_loan_count=random.randint(0, 1),
            flash_loan_providers=["aave_v3"] if random.random() < 0.4 else [],
            flash_loan_amounts=[], total_borrowed=random.randint(0, 30000000),
            has_callback=random.random() < 0.4, callback_selectors=[],
            nested_flash_loans=False, repayment_detected=random.random() < 0.4,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(10, 35),
            unique_contracts_modified=random.randint(2, 6),
            unique_slots_modified=random.randint(6, 22),
            balance_slot_changes=random.randint(3, 10),
            large_value_changes=random.randint(2, 8),
            max_value_delta=random.randint(1000000, 50000000),
            avg_value_delta=random.randint(500000, 20000000),
            variance_ratio=random.uniform(0.4, 0.8),
            zero_to_nonzero=random.randint(1, 4),
            nonzero_to_zero=random.randint(1, 4),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(4000, 15000), bytecode_hash="0xrounding",
            is_contract=True, is_proxy=random.random() < 0.3, proxy_type=None,
            contract_age_blocks=random.randint(100, 2000), is_verified=random.random() < 0.5,
            matches_known_exploit=random.random() < 0.15, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.1, 0.3), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.4, has_create2=False,
            unique_opcodes=random.randint(50, 90),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(8, 30), call_depth=random.randint(2, 7),
            delegatecall_count=random.randint(0, 3), staticcall_count=random.randint(3, 10),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(6, 25), internal_calls=random.randint(4, 15),
            external_calls=random.randint(4, 15), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(1, 6),
            gas_forwarded_ratio=random.uniform(0.65, 0.9), revert_count=random.randint(0, 2),
        ),
        metadata={"type": "rounding_error", "label": 1},
    )


def _mint_vulnerability_exploit() -> AggregatedFeatures:
    """PlayDapp 2024, Gala Games 2024 style - unauthorized minting."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=False, flash_loan_count=0, flash_loan_providers=[],
            flash_loan_amounts=[], total_borrowed=0, has_callback=False,
            callback_selectors=[], nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(5, 20),
            unique_contracts_modified=random.randint(1, 4),
            unique_slots_modified=random.randint(3, 12),
            balance_slot_changes=random.randint(2, 8),
            large_value_changes=random.randint(2, 10),
            max_value_delta=random.randint(100000000, 999999999),
            avg_value_delta=random.randint(50000000, 500000000),
            variance_ratio=random.uniform(0.5, 0.9),
            zero_to_nonzero=random.randint(2, 8),
            nonzero_to_zero=random.randint(0, 2),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(2000, 10000), bytecode_hash="0xmint",
            is_contract=True, is_proxy=random.random() < 0.4, proxy_type=None,
            contract_age_blocks=random.randint(500, 5000), is_verified=random.random() < 0.7,
            matches_known_exploit=random.random() < 0.1, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.05, 0.25), has_selfdestruct=False,
            has_delegatecall=random.random() < 0.3, has_create2=False,
            unique_opcodes=random.randint(40, 75),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(3, 15), call_depth=random.randint(1, 4),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(1, 5),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(2, 12), internal_calls=random.randint(1, 8),
            external_calls=random.randint(2, 8), unique_call_types=random.randint(1, 3),
            call_value_transfers=random.randint(0, 3),
            gas_forwarded_ratio=random.uniform(0.5, 0.8), revert_count=0,
        ),
        metadata={"type": "mint_vulnerability", "label": 1},
    )


def _compiler_bug_exploit() -> AggregatedFeatures:
    """Curve 2023 style - Vyper compiler reentrancy bug."""
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.5, flash_loan_count=random.randint(0, 1),
            flash_loan_providers=["balancer"] if random.random() < 0.5 else [],
            flash_loan_amounts=[], total_borrowed=random.randint(0, 80000000),
            has_callback=True, callback_selectors=["fallback"],
            nested_flash_loans=False, repayment_detected=random.random() < 0.5,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(25, 120),
            unique_contracts_modified=random.randint(2, 5),
            unique_slots_modified=random.randint(8, 30),
            balance_slot_changes=random.randint(8, 40),
            large_value_changes=random.randint(4, 18),
            max_value_delta=random.randint(20000000, 250000000),
            avg_value_delta=random.randint(5000000, 80000000),
            variance_ratio=random.uniform(0.35, 0.8),
            zero_to_nonzero=random.randint(1, 5),
            nonzero_to_zero=random.randint(5, 25),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(3000, 12000), bytecode_hash="0xcompiler",
            is_contract=True, is_proxy=False, proxy_type=None,
            contract_age_blocks=random.randint(0, 30), is_verified=False,
            matches_known_exploit=random.random() < 0.3, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.25, 0.5), has_selfdestruct=random.random() < 0.1,
            has_delegatecall=random.random() < 0.2, has_create2=random.random() < 0.15,
            unique_opcodes=random.randint(40, 75),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(25, 150), call_depth=random.randint(6, 25),
            delegatecall_count=random.randint(0, 2), staticcall_count=random.randint(2, 8),
            create_count=0, create2_count=0, selfdestruct_count=0,
            call_count=random.randint(20, 120), internal_calls=random.randint(15, 80),
            external_calls=random.randint(5, 30), unique_call_types=random.randint(2, 4),
            call_value_transfers=random.randint(8, 40),
            gas_forwarded_ratio=random.uniform(0.85, 0.99), revert_count=random.randint(0, 5),
        ),
        metadata={"type": "compiler_bug", "label": 1},
    )


def _generic_exploit() -> AggregatedFeatures:
    return AggregatedFeatures(
        flash_loan=FlashLoanFeatures(
            has_flash_loan=random.random() < 0.5, flash_loan_count=random.randint(0, 2),
            flash_loan_providers=[], flash_loan_amounts=[], total_borrowed=0,
            has_callback=random.random() < 0.5, callback_selectors=[],
            nested_flash_loans=False, repayment_detected=False,
        ),
        state_variance=StateVarianceFeatures(
            total_storage_changes=random.randint(15, 60),
            unique_contracts_modified=random.randint(3, 10),
            unique_slots_modified=random.randint(10, 35),
            balance_slot_changes=random.randint(3, 12),
            large_value_changes=random.randint(2, 10),
            max_value_delta=random.randint(10000000, 200000000),
            avg_value_delta=random.randint(5000000, 80000000),
            variance_ratio=random.uniform(0.3, 0.7),
            zero_to_nonzero=random.randint(1, 6),
            nonzero_to_zero=random.randint(1, 6),
        ),
        bytecode=BytecodeFeatures(
            bytecode_length=random.randint(2000, 15000), bytecode_hash="0xexploit6",
            is_contract=True, is_proxy=random.random() < 0.2, proxy_type=None,
            contract_age_blocks=random.randint(0, 500), is_verified=random.random() < 0.3,
            matches_known_exploit=random.random() < 0.1, matched_exploit_id=None,
            jaccard_similarity=random.uniform(0.1, 0.3), has_selfdestruct=random.random() < 0.15,
            has_delegatecall=random.random() < 0.35, has_create2=random.random() < 0.2,
            unique_opcodes=random.randint(40, 85),
        ),
        opcode=OpcodeFeatures(
            total_calls=random.randint(10, 50), call_depth=random.randint(3, 10),
            delegatecall_count=random.randint(0, 3), staticcall_count=random.randint(2, 10),
            create_count=random.randint(0, 2), create2_count=random.randint(0, 1),
            selfdestruct_count=random.randint(0, 1), call_count=random.randint(8, 40),
            internal_calls=random.randint(5, 25), external_calls=random.randint(5, 25),
            unique_call_types=random.randint(3, 5), call_value_transfers=random.randint(2, 8),
            gas_forwarded_ratio=random.uniform(0.7, 0.95), revert_count=random.randint(0, 3),
        ),
        metadata={"type": "generic_exploit", "label": 1},
    )


def generate_training_data(
    n_benign: int = 900,
    n_exploits: int = 100,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    random.seed(seed)
    np.random.seed(seed)

    registry = ExploitRegistry()
    trainable = [e for e in registry.get_trainable() if e.detectability == Detectability.HIGH]

    attack_vectors = [
        AttackVector.FLASH_LOAN,
        AttackVector.ORACLE_MANIPULATION,
        AttackVector.REENTRANCY,
        AttackVector.LOGIC_ERROR,
        AttackVector.GOVERNANCE_ATTACK,
        AttackVector.ARITHMETIC_OVERFLOW,
        AttackVector.DONATION_ATTACK,
        AttackVector.APPROVAL_EXPLOIT,
        AttackVector.ROUNDING_ERROR,
        AttackVector.MINT_VULNERABILITY,
        AttackVector.COMPILER_BUG,
    ]

    all_features: list[AggregatedFeatures] = []
    metadata_list: list[dict] = []

    logger.info("generating_benign_samples", count=n_benign)
    for i in range(n_benign):
        features = generate_benign_features()
        all_features.append(features)
        metadata_list.append(features.metadata)

    logger.info("generating_exploit_samples", count=n_exploits)
    for i in range(n_exploits):
        attack_vector = random.choice(attack_vectors)
        features = generate_exploit_features(attack_vector)
        all_features.append(features)
        metadata_list.append(features.metadata)

    X = np.array([f.to_vector() for f in all_features])
    y = np.array([f.metadata["label"] for f in all_features])

    logger.info(
        "training_data_generated",
        total_samples=len(X),
        benign=n_benign,
        exploits=n_exploits,
        feature_dim=X.shape[1],
    )

    return X, y, metadata_list


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic training data")
    parser.add_argument("--benign", type=int, default=900, help="Number of benign samples")
    parser.add_argument("--exploits", type=int, default=100, help="Number of exploit samples")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, default="training_data.npz", help="Output file")

    args = parser.parse_args()

    X, y, metadata = generate_training_data(
        n_benign=args.benign,
        n_exploits=args.exploits,
        seed=args.seed,
    )

    output_path = Path(args.output)
    np.savez(output_path, X=X, y=y)

    metadata_path = output_path.with_suffix(".json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(
        "data_saved",
        features_file=str(output_path),
        metadata_file=str(metadata_path),
        shape=X.shape,
    )


if __name__ == "__main__":
    main()

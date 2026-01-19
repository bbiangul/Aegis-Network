from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
from web3 import AsyncWeb3

from sentinel_brain.data.collectors.fork_replayer import TransactionTrace
from sentinel_brain.data.collectors.mempool_listener import PendingTransaction
from sentinel_brain.features.extractors.flash_loan import FlashLoanExtractor, FlashLoanFeatures
from sentinel_brain.features.extractors.state_variance import StateVarianceExtractor, StateVarianceFeatures
from sentinel_brain.features.extractors.bytecode import BytecodeExtractor, BytecodeFeatures
from sentinel_brain.features.extractors.opcode import OpcodeExtractor, OpcodeFeatures


@dataclass
class AggregatedFeatures:
    flash_loan: FlashLoanFeatures
    state_variance: StateVarianceFeatures
    bytecode: BytecodeFeatures
    opcode: OpcodeFeatures
    metadata: dict[str, Any]

    def to_vector(self) -> np.ndarray:
        flash_loan_vec = self.flash_loan.to_vector()
        state_vec = self.state_variance.to_vector()
        bytecode_vec = self.bytecode.to_vector()
        opcode_vec = self.opcode.to_vector()

        combined = flash_loan_vec + state_vec + bytecode_vec + opcode_vec
        return np.array(combined, dtype=np.float32)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flash_loan": {
                "has_flash_loan": self.flash_loan.has_flash_loan,
                "count": self.flash_loan.flash_loan_count,
                "providers": self.flash_loan.flash_loan_providers,
                "total_borrowed": self.flash_loan.total_borrowed,
                "has_callback": self.flash_loan.has_callback,
                "nested": self.flash_loan.nested_flash_loans,
            },
            "state_variance": {
                "storage_changes": self.state_variance.total_storage_changes,
                "contracts_modified": self.state_variance.unique_contracts_modified,
                "large_changes": self.state_variance.large_value_changes,
                "max_delta": self.state_variance.max_value_delta,
                "variance_ratio": self.state_variance.variance_ratio,
            },
            "bytecode": {
                "is_contract": self.bytecode.is_contract,
                "is_proxy": self.bytecode.is_proxy,
                "proxy_type": self.bytecode.proxy_type,
                "age_blocks": self.bytecode.contract_age_blocks,
                "matches_exploit": self.bytecode.matches_known_exploit,
                "jaccard_similarity": self.bytecode.jaccard_similarity,
                "has_selfdestruct": self.bytecode.has_selfdestruct,
                "has_delegatecall": self.bytecode.has_delegatecall,
            },
            "opcode": {
                "total_calls": self.opcode.total_calls,
                "call_depth": self.opcode.call_depth,
                "delegatecall_count": self.opcode.delegatecall_count,
                "create2_count": self.opcode.create2_count,
                "selfdestruct_count": self.opcode.selfdestruct_count,
                "gas_ratio": self.opcode.gas_forwarded_ratio,
            },
            "metadata": self.metadata,
        }

    @property
    def feature_names(self) -> list[str]:
        return [
            "fl_has_flash_loan",
            "fl_count",
            "fl_provider_count",
            "fl_total_borrowed",
            "fl_has_callback",
            "fl_callback_count",
            "fl_nested",
            "fl_repayment",
            "sv_storage_changes",
            "sv_contracts_modified",
            "sv_slots_modified",
            "sv_balance_changes",
            "sv_large_changes",
            "sv_max_delta",
            "sv_avg_delta",
            "sv_variance_ratio",
            "sv_zero_to_nonzero",
            "sv_nonzero_to_zero",
            "bc_length",
            "bc_is_contract",
            "bc_is_proxy",
            "bc_age_blocks",
            "bc_is_verified",
            "bc_matches_exploit",
            "bc_jaccard",
            "bc_has_selfdestruct",
            "bc_has_delegatecall",
            "bc_has_create2",
            "bc_unique_opcodes",
            "op_total_calls",
            "op_call_depth",
            "op_delegatecall",
            "op_staticcall",
            "op_create",
            "op_create2",
            "op_selfdestruct",
            "op_call",
            "op_internal_calls",
            "op_external_calls",
            "op_unique_types",
            "op_value_transfers",
            "op_gas_ratio",
            "op_revert_count",
        ]


class FeatureAggregator:
    def __init__(
        self,
        flash_loan_extractor: FlashLoanExtractor | None = None,
        state_variance_extractor: StateVarianceExtractor | None = None,
        bytecode_extractor: BytecodeExtractor | None = None,
        opcode_extractor: OpcodeExtractor | None = None,
    ):
        self.flash_loan = flash_loan_extractor or FlashLoanExtractor()
        self.state_variance = state_variance_extractor or StateVarianceExtractor()
        self.bytecode = bytecode_extractor or BytecodeExtractor()
        self.opcode = opcode_extractor or OpcodeExtractor()

    async def extract_from_trace(
        self,
        trace: TransactionTrace,
        w3: AsyncWeb3 | None = None,
    ) -> AggregatedFeatures:
        flash_loan_features = self.flash_loan.extract(trace)
        state_features = self.state_variance.extract(trace)
        opcode_features = self.opcode.extract(trace)

        if trace.to_address is None:
            bytecode_features = self.bytecode.extract_from_bytecode(trace.input_data)
        elif w3 is not None and trace.to_address:
            bytecode_features = await self.bytecode.extract(
                trace.to_address, w3, trace.block_number
            )
        else:
            bytecode_features = self.bytecode._empty_features()

        metadata = {
            "tx_hash": trace.tx_hash,
            "block_number": trace.block_number,
            "from": trace.from_address,
            "to": trace.to_address,
            "value": trace.value,
            "gas_used": trace.gas_used,
            "status": trace.status,
            "contracts_called": len(trace.contracts_called),
            "created_contracts": len(trace.created_contracts),
        }

        return AggregatedFeatures(
            flash_loan=flash_loan_features,
            state_variance=state_features,
            bytecode=bytecode_features,
            opcode=opcode_features,
            metadata=metadata,
        )

    def extract_from_pending(self, tx: PendingTransaction) -> AggregatedFeatures:
        flash_loan_features = self.flash_loan.extract_from_input(tx.input_data, tx.to_address)

        state_features = StateVarianceFeatures(
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

        if tx.is_contract_creation:
            bytecode_features = self.bytecode.extract_from_bytecode(tx.input_data)
        else:
            bytecode_features = self.bytecode._empty_features()

        opcode_features = OpcodeFeatures(
            total_calls=0,
            call_depth=0,
            delegatecall_count=0,
            staticcall_count=0,
            create_count=1 if tx.is_contract_creation else 0,
            create2_count=0,
            selfdestruct_count=0,
            call_count=1 if tx.is_contract_interaction else 0,
            internal_calls=0,
            external_calls=1 if tx.is_contract_interaction else 0,
            unique_call_types=1,
            call_value_transfers=1 if tx.value > 0 else 0,
            gas_forwarded_ratio=0.0,
            revert_count=0,
        )

        metadata = {
            "tx_hash": tx.hash,
            "from": tx.from_address,
            "to": tx.to_address,
            "value": tx.value,
            "gas": tx.gas,
            "is_contract_interaction": tx.is_contract_interaction,
            "is_contract_creation": tx.is_contract_creation,
            "selector": tx.selector,
        }

        return AggregatedFeatures(
            flash_loan=flash_loan_features,
            state_variance=state_features,
            bytecode=bytecode_features,
            opcode=opcode_features,
            metadata=metadata,
        )

    async def extract_batch(
        self,
        traces: list[TransactionTrace],
        w3: AsyncWeb3 | None = None,
    ) -> list[AggregatedFeatures]:
        tasks = [self.extract_from_trace(trace, w3) for trace in traces]
        return await asyncio.gather(*tasks)

    def to_feature_matrix(self, features_list: list[AggregatedFeatures]) -> np.ndarray:
        if not features_list:
            return np.array([])

        vectors = [f.to_vector() for f in features_list]
        return np.stack(vectors)

    def get_feature_names(self) -> list[str]:
        dummy = AggregatedFeatures(
            flash_loan=FlashLoanFeatures(False, 0, [], [], 0, False, [], False, False),
            state_variance=StateVarianceFeatures(0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0),
            bytecode=BytecodeFeatures(0, "", False, False, None, 0, False, False, None, 0.0, False, False, False, 0),
            opcode=OpcodeFeatures(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0),
            metadata={},
        )
        return dummy.feature_names

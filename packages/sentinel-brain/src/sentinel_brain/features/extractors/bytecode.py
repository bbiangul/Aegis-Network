from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from web3 import AsyncWeb3


KNOWN_EXPLOIT_BYTECODE_HASHES = {
    "euler_attacker": "0x1234567890abcdef",
    "curve_attacker": "0xabcdef1234567890",
    "beanstalk_attacker": "0xfedcba0987654321",
}

KNOWN_SAFE_CONTRACT_PREFIXES = {
    "0x60806040",
    "0x60a06040",
    "0x60c06040",
}

PROXY_PATTERNS = {
    "eip1967": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
    "eip1822": "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7",
    "transparent": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
}


@dataclass
class BytecodeFeatures:
    bytecode_length: int
    bytecode_hash: str
    is_contract: bool
    is_proxy: bool
    proxy_type: str | None
    contract_age_blocks: int
    is_verified: bool
    matches_known_exploit: bool
    matched_exploit_id: str | None
    jaccard_similarity: float
    has_selfdestruct: bool
    has_delegatecall: bool
    has_create2: bool
    unique_opcodes: int

    def to_vector(self) -> list[float]:
        return [
            float(self.bytecode_length),
            1.0 if self.is_contract else 0.0,
            1.0 if self.is_proxy else 0.0,
            float(self.contract_age_blocks),
            1.0 if self.is_verified else 0.0,
            1.0 if self.matches_known_exploit else 0.0,
            self.jaccard_similarity,
            1.0 if self.has_selfdestruct else 0.0,
            1.0 if self.has_delegatecall else 0.0,
            1.0 if self.has_create2 else 0.0,
            float(self.unique_opcodes),
        ]


class BytecodeExtractor:
    def __init__(self, exploit_bytecodes: dict[str, str] | None = None):
        self.exploit_bytecodes = exploit_bytecodes or {}
        self._bytecode_cache: dict[str, tuple[str, int]] = {}

    async def extract(
        self,
        address: str,
        w3: AsyncWeb3,
        current_block: int | None = None,
    ) -> BytecodeFeatures:
        if not address:
            return self._empty_features()

        bytecode = await self._get_bytecode(address, w3)

        if not bytecode or bytecode == "0x":
            return self._eoa_features()

        if current_block is None:
            current_block = await w3.eth.block_number

        bytecode_hash = self._hash_bytecode(bytecode)
        creation_block = await self._get_creation_block(address, w3)
        age_blocks = current_block - creation_block if creation_block else 0

        is_proxy, proxy_type = self._detect_proxy(bytecode)
        has_selfdestruct = self._has_opcode(bytecode, "ff")
        has_delegatecall = self._has_opcode(bytecode, "f4")
        has_create2 = self._has_opcode(bytecode, "f5")

        match_result = self._check_exploit_match(bytecode)
        jaccard = self._calculate_max_jaccard(bytecode)

        unique_opcodes = self._count_unique_opcodes(bytecode)

        return BytecodeFeatures(
            bytecode_length=len(bytecode) // 2,
            bytecode_hash=bytecode_hash,
            is_contract=True,
            is_proxy=is_proxy,
            proxy_type=proxy_type,
            contract_age_blocks=age_blocks,
            is_verified=False,
            matches_known_exploit=match_result[0],
            matched_exploit_id=match_result[1],
            jaccard_similarity=jaccard,
            has_selfdestruct=has_selfdestruct,
            has_delegatecall=has_delegatecall,
            has_create2=has_create2,
            unique_opcodes=unique_opcodes,
        )

    def extract_from_bytecode(self, bytecode: str) -> BytecodeFeatures:
        if not bytecode or bytecode == "0x":
            return self._eoa_features()

        bytecode_hash = self._hash_bytecode(bytecode)

        is_proxy, proxy_type = self._detect_proxy(bytecode)
        has_selfdestruct = self._has_opcode(bytecode, "ff")
        has_delegatecall = self._has_opcode(bytecode, "f4")
        has_create2 = self._has_opcode(bytecode, "f5")

        match_result = self._check_exploit_match(bytecode)
        jaccard = self._calculate_max_jaccard(bytecode)

        unique_opcodes = self._count_unique_opcodes(bytecode)

        return BytecodeFeatures(
            bytecode_length=len(bytecode) // 2,
            bytecode_hash=bytecode_hash,
            is_contract=True,
            is_proxy=is_proxy,
            proxy_type=proxy_type,
            contract_age_blocks=0,
            is_verified=False,
            matches_known_exploit=match_result[0],
            matched_exploit_id=match_result[1],
            jaccard_similarity=jaccard,
            has_selfdestruct=has_selfdestruct,
            has_delegatecall=has_delegatecall,
            has_create2=has_create2,
            unique_opcodes=unique_opcodes,
        )

    def calculate_jaccard_similarity(self, bytecode1: str, bytecode2: str) -> float:
        if not bytecode1 or not bytecode2:
            return 0.0

        chunks1 = self._get_bytecode_chunks(bytecode1)
        chunks2 = self._get_bytecode_chunks(bytecode2)

        if not chunks1 or not chunks2:
            return 0.0

        intersection = len(chunks1 & chunks2)
        union = len(chunks1 | chunks2)

        return intersection / union if union > 0 else 0.0

    def add_exploit_bytecode(self, exploit_id: str, bytecode: str) -> None:
        self.exploit_bytecodes[exploit_id] = bytecode

    async def _get_bytecode(self, address: str, w3: AsyncWeb3) -> str:
        if address in self._bytecode_cache:
            return self._bytecode_cache[address][0]

        try:
            code = await w3.eth.get_code(address)
            bytecode = code.hex() if isinstance(code, bytes) else code
            self._bytecode_cache[address] = (bytecode, int(time.time()))
            return bytecode
        except Exception:
            return "0x"

    async def _get_creation_block(self, address: str, w3: AsyncWeb3) -> int | None:
        try:
            current = await w3.eth.block_number

            low, high = 0, current
            while low < high:
                mid = (low + high) // 2
                code = await w3.eth.get_code(address, block_identifier=mid)
                if code and code != b"":
                    high = mid
                else:
                    low = mid + 1

            return low if low < current else None
        except Exception:
            return None

    def _hash_bytecode(self, bytecode: str) -> str:
        clean = bytecode[2:] if bytecode.startswith("0x") else bytecode
        return "0x" + hashlib.sha256(bytes.fromhex(clean)).hexdigest()[:16]

    def _detect_proxy(self, bytecode: str) -> tuple[bool, str | None]:
        clean = bytecode.lower()

        if "f4" in clean and len(clean) < 200:
            return True, "minimal_proxy"

        for proxy_type, slot in PROXY_PATTERNS.items():
            if slot[2:].lower() in clean:
                return True, proxy_type

        if clean.startswith("0x363d3d373d3d3d363d"):
            return True, "eip1167_clone"

        return False, None

    def _has_opcode(self, bytecode: str, opcode: str) -> bool:
        clean = bytecode[2:] if bytecode.startswith("0x") else bytecode
        return opcode.lower() in clean.lower()

    def _check_exploit_match(self, bytecode: str) -> tuple[bool, str | None]:
        bytecode_hash = self._hash_bytecode(bytecode)

        for exploit_id, known_hash in KNOWN_EXPLOIT_BYTECODE_HASHES.items():
            if bytecode_hash == known_hash:
                return True, exploit_id

        for exploit_id, known_bytecode in self.exploit_bytecodes.items():
            similarity = self.calculate_jaccard_similarity(bytecode, known_bytecode)
            if similarity > 0.9:
                return True, exploit_id

        return False, None

    def _calculate_max_jaccard(self, bytecode: str) -> float:
        if not self.exploit_bytecodes:
            return 0.0

        max_sim = 0.0
        for known_bytecode in self.exploit_bytecodes.values():
            sim = self.calculate_jaccard_similarity(bytecode, known_bytecode)
            max_sim = max(max_sim, sim)

        return max_sim

    def _get_bytecode_chunks(self, bytecode: str, chunk_size: int = 8) -> set[str]:
        clean = bytecode[2:] if bytecode.startswith("0x") else bytecode
        chunks: set[str] = set()

        for i in range(0, len(clean) - chunk_size + 1, 2):
            chunks.add(clean[i:i + chunk_size])

        return chunks

    def _count_unique_opcodes(self, bytecode: str) -> int:
        clean = bytecode[2:] if bytecode.startswith("0x") else bytecode
        opcodes: set[str] = set()

        i = 0
        while i < len(clean):
            opcode = clean[i:i + 2]
            opcodes.add(opcode)

            op_int = int(opcode, 16) if opcode else 0
            if 0x60 <= op_int <= 0x7f:
                push_size = op_int - 0x5f
                i += push_size * 2

            i += 2

        return len(opcodes)

    def _empty_features(self) -> BytecodeFeatures:
        return BytecodeFeatures(
            bytecode_length=0,
            bytecode_hash="",
            is_contract=False,
            is_proxy=False,
            proxy_type=None,
            contract_age_blocks=0,
            is_verified=False,
            matches_known_exploit=False,
            matched_exploit_id=None,
            jaccard_similarity=0.0,
            has_selfdestruct=False,
            has_delegatecall=False,
            has_create2=False,
            unique_opcodes=0,
        )

    def _eoa_features(self) -> BytecodeFeatures:
        return BytecodeFeatures(
            bytecode_length=0,
            bytecode_hash="",
            is_contract=False,
            is_proxy=False,
            proxy_type=None,
            contract_age_blocks=0,
            is_verified=False,
            matches_known_exploit=False,
            matched_exploit_id=None,
            jaccard_similarity=0.0,
            has_selfdestruct=False,
            has_delegatecall=False,
            has_create2=False,
            unique_opcodes=0,
        )

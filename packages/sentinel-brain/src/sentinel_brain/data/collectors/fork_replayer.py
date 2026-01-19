from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.types import TxReceipt, TxData
from hexbytes import HexBytes

from sentinel_brain.data.exploits import Exploit


logger = structlog.get_logger()


@dataclass
class TraceLog:
    address: str
    topics: list[str]
    data: str


@dataclass
class TraceCall:
    call_type: str
    from_address: str
    to_address: str
    value: int
    gas: int
    gas_used: int
    input_data: str
    output_data: str
    depth: int
    children: list[TraceCall] = field(default_factory=list)


@dataclass
class StorageChange:
    address: str
    slot: str
    previous_value: str
    new_value: str


@dataclass
class TransactionTrace:
    tx_hash: str
    block_number: int
    from_address: str
    to_address: str | None
    value: int
    gas_used: int
    gas_price: int
    input_data: str
    status: bool
    logs: list[TraceLog]
    call_trace: TraceCall | None
    storage_changes: list[StorageChange]
    opcodes: dict[str, int]
    contracts_called: list[str]
    created_contracts: list[str]
    selfdestruct_contracts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "value": self.value,
            "gas_used": self.gas_used,
            "gas_price": self.gas_price,
            "input_data": self.input_data,
            "status": self.status,
            "logs": [{"address": l.address, "topics": l.topics, "data": l.data} for l in self.logs],
            "storage_changes": [
                {"address": s.address, "slot": s.slot, "previous": s.previous_value, "new": s.new_value}
                for s in self.storage_changes
            ],
            "opcodes": self.opcodes,
            "contracts_called": self.contracts_called,
            "created_contracts": self.created_contracts,
            "selfdestruct_contracts": self.selfdestruct_contracts,
        }


class AnvilInstance:
    def __init__(
        self,
        rpc_url: str,
        fork_block: int | None = None,
        port: int = 8545,
        anvil_path: str = "anvil",
    ):
        self.rpc_url = rpc_url
        self.fork_block = fork_block
        self.port = port
        self.anvil_path = anvil_path
        self.process: subprocess.Popen | None = None
        self.local_rpc = f"http://127.0.0.1:{port}"

    async def start(self) -> None:
        cmd = [
            self.anvil_path,
            "--fork-url", self.rpc_url,
            "--port", str(self.port),
            "--steps-tracing",
            "--timeout", "300000",
        ]
        if self.fork_block:
            cmd.extend(["--fork-block-number", str(self.fork_block)])

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        await self._wait_for_ready()
        logger.info("anvil_started", port=self.port, fork_block=self.fork_block)

    async def _wait_for_ready(self, timeout: float = 120.0) -> None:
        start = time.time()
        w3 = AsyncWeb3(AsyncHTTPProvider(self.local_rpc))

        while time.time() - start < timeout:
            try:
                if await w3.is_connected():
                    return
            except Exception:
                pass
            await asyncio.sleep(0.1)

        raise TimeoutError(f"Anvil did not start within {timeout}s")

    async def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            logger.info("anvil_stopped")

    async def __aenter__(self) -> AnvilInstance:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()


class ForkReplayer:
    def __init__(
        self,
        rpc_url: str,
        anvil_path: str = "anvil",
        output_dir: str | Path = "data/traces",
    ):
        self.rpc_url = rpc_url
        self.anvil_path = anvil_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def replay_transaction(
        self,
        tx_hash: str,
        fork_block: int | None = None,
    ) -> TransactionTrace:
        port = 8545 + hash(tx_hash) % 1000

        origin_w3 = AsyncWeb3(AsyncHTTPProvider(self.rpc_url))

        tx = await self._get_transaction(origin_w3, tx_hash)
        if not tx:
            raise ValueError(f"Transaction {tx_hash} not found on origin RPC")

        tx_block = tx["blockNumber"]

        async with AnvilInstance(
            rpc_url=self.rpc_url,
            fork_block=tx_block,
            port=port,
            anvil_path=self.anvil_path,
        ) as anvil:
            anvil_w3 = AsyncWeb3(AsyncHTTPProvider(anvil.local_rpc))

            trace = await self._trace_transaction(anvil_w3, tx_hash)
            receipt = await anvil_w3.eth.get_transaction_receipt(tx_hash)

            return self._build_trace(tx, receipt, trace)

    async def replay_exploit(self, exploit: Exploit) -> TransactionTrace | None:
        if not exploit.tx_hash:
            logger.warning("exploit_no_tx_hash", exploit_id=exploit.id)
            return None

        try:
            trace = await self.replay_transaction(exploit.tx_hash)
            self._save_trace(exploit.id, trace)
            logger.info("exploit_replayed", exploit_id=exploit.id, tx_hash=exploit.tx_hash)
            return trace
        except Exception as e:
            logger.error("exploit_replay_failed", exploit_id=exploit.id, error=str(e))
            raise

    async def replay_exploits(self, exploits: list[Exploit]) -> dict[str, TransactionTrace]:
        results: dict[str, TransactionTrace] = {}

        for exploit in exploits:
            if not exploit.tx_hash:
                continue
            try:
                trace = await self.replay_exploit(exploit)
                if trace:
                    results[exploit.id] = trace
            except Exception as e:
                logger.error("batch_replay_error", exploit_id=exploit.id, error=str(e))

        return results

    async def _get_transaction(self, w3: AsyncWeb3, tx_hash: str) -> TxData | None:
        try:
            return await w3.eth.get_transaction(HexBytes(tx_hash))
        except Exception:
            return None

    async def _trace_transaction(self, w3: AsyncWeb3, tx_hash: str) -> dict[str, Any]:
        try:
            trace = await w3.provider.make_request(
                "debug_traceTransaction",
                [tx_hash, {"tracer": "callTracer", "tracerConfig": {"withLog": True}}],
            )
            return trace.get("result", {})
        except Exception as e:
            logger.warning("trace_failed", tx_hash=tx_hash, error=str(e))
            return {}

    async def _get_storage_diff(self, w3: AsyncWeb3, tx_hash: str) -> list[dict[str, Any]]:
        try:
            result = await w3.provider.make_request(
                "debug_traceTransaction",
                [tx_hash, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}],
            )
            return result.get("result", {})
        except Exception:
            return []

    def _build_trace(
        self,
        tx: TxData,
        receipt: TxReceipt,
        call_trace: dict[str, Any],
    ) -> TransactionTrace:
        logs = [
            TraceLog(
                address=log["address"],
                topics=[t.hex() if isinstance(t, bytes) else t for t in log["topics"]],
                data=log["data"].hex() if isinstance(log["data"], bytes) else log["data"],
            )
            for log in receipt.get("logs", [])
        ]

        opcodes = self._extract_opcodes(call_trace)
        contracts_called = self._extract_contracts_called(call_trace)
        created, destroyed = self._extract_contract_lifecycle(call_trace)

        call_tree = self._parse_call_trace(call_trace) if call_trace else None

        return TransactionTrace(
            tx_hash=tx["hash"].hex() if isinstance(tx["hash"], bytes) else tx["hash"],
            block_number=tx["blockNumber"],
            from_address=tx["from"],
            to_address=tx.get("to"),
            value=tx["value"],
            gas_used=receipt["gasUsed"],
            gas_price=tx.get("gasPrice", 0),
            input_data=tx["input"].hex() if isinstance(tx["input"], bytes) else tx["input"],
            status=receipt["status"] == 1,
            logs=logs,
            call_trace=call_tree,
            storage_changes=[],
            opcodes=opcodes,
            contracts_called=contracts_called,
            created_contracts=created,
            selfdestruct_contracts=destroyed,
        )

    def _parse_call_trace(self, trace: dict[str, Any], depth: int = 0) -> TraceCall:
        children = []
        for call in trace.get("calls", []):
            children.append(self._parse_call_trace(call, depth + 1))

        return TraceCall(
            call_type=trace.get("type", "CALL"),
            from_address=trace.get("from", ""),
            to_address=trace.get("to", ""),
            value=int(trace.get("value", "0x0"), 16) if trace.get("value") else 0,
            gas=int(trace.get("gas", "0x0"), 16) if trace.get("gas") else 0,
            gas_used=int(trace.get("gasUsed", "0x0"), 16) if trace.get("gasUsed") else 0,
            input_data=trace.get("input", ""),
            output_data=trace.get("output", ""),
            depth=depth,
            children=children,
        )

    def _extract_opcodes(self, trace: dict[str, Any]) -> dict[str, int]:
        opcodes: dict[str, int] = {}

        def count_type(t: dict[str, Any]) -> None:
            call_type = t.get("type", "CALL")
            opcodes[call_type] = opcodes.get(call_type, 0) + 1
            for child in t.get("calls", []):
                count_type(child)

        if trace:
            count_type(trace)
        return opcodes

    def _extract_contracts_called(self, trace: dict[str, Any]) -> list[str]:
        contracts: set[str] = set()

        def extract(t: dict[str, Any]) -> None:
            if to_addr := t.get("to"):
                contracts.add(to_addr.lower())
            for child in t.get("calls", []):
                extract(child)

        if trace:
            extract(trace)
        return list(contracts)

    def _extract_contract_lifecycle(self, trace: dict[str, Any]) -> tuple[list[str], list[str]]:
        created: list[str] = []
        destroyed: list[str] = []

        def extract(t: dict[str, Any]) -> None:
            call_type = t.get("type", "")
            if call_type in ("CREATE", "CREATE2"):
                if to_addr := t.get("to"):
                    created.append(to_addr.lower())
            elif call_type == "SELFDESTRUCT":
                if from_addr := t.get("from"):
                    destroyed.append(from_addr.lower())
            for child in t.get("calls", []):
                extract(child)

        if trace:
            extract(trace)
        return created, destroyed

    def _save_trace(self, exploit_id: str, trace: TransactionTrace) -> None:
        output_path = self.output_dir / f"{exploit_id}.json"
        with open(output_path, "w") as f:
            json.dump(trace.to_dict(), f, indent=2)
        logger.info("trace_saved", path=str(output_path))

    def load_trace(self, exploit_id: str) -> TransactionTrace | None:
        path = self.output_dir / f"{exploit_id}.json"
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)

        return TransactionTrace(
            tx_hash=data["tx_hash"],
            block_number=data["block_number"],
            from_address=data["from_address"],
            to_address=data["to_address"],
            value=data["value"],
            gas_used=data["gas_used"],
            gas_price=data["gas_price"],
            input_data=data["input_data"],
            status=data["status"],
            logs=[TraceLog(**l) for l in data["logs"]],
            call_trace=None,
            storage_changes=[StorageChange(**s) for s in data["storage_changes"]],
            opcodes=data["opcodes"],
            contracts_called=data["contracts_called"],
            created_contracts=data["created_contracts"],
            selfdestruct_contracts=data["selfdestruct_contracts"],
        )

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

import aiohttp
import structlog
from web3 import AsyncWeb3, AsyncHTTPProvider
from web3.providers import WebsocketProviderV2 as WebSocketProvider
from web3.types import TxData
from hexbytes import HexBytes


logger = structlog.get_logger()


@dataclass
class PendingTransaction:
    hash: str
    from_address: str
    to_address: str | None
    value: int
    gas: int
    gas_price: int
    max_fee_per_gas: int | None
    max_priority_fee_per_gas: int | None
    input_data: str
    nonce: int
    chain_id: int | None

    @classmethod
    def from_tx_data(cls, tx: TxData) -> PendingTransaction:
        return cls(
            hash=tx["hash"].hex() if isinstance(tx["hash"], bytes) else tx["hash"],
            from_address=tx["from"],
            to_address=tx.get("to"),
            value=tx["value"],
            gas=tx["gas"],
            gas_price=tx.get("gasPrice", 0),
            max_fee_per_gas=tx.get("maxFeePerGas"),
            max_priority_fee_per_gas=tx.get("maxPriorityFeePerGas"),
            input_data=tx["input"].hex() if isinstance(tx["input"], bytes) else tx["input"],
            nonce=tx["nonce"],
            chain_id=tx.get("chainId"),
        )

    @property
    def is_contract_interaction(self) -> bool:
        return self.to_address is not None and len(self.input_data) > 2

    @property
    def is_contract_creation(self) -> bool:
        return self.to_address is None and len(self.input_data) > 2

    @property
    def is_simple_transfer(self) -> bool:
        return self.input_data == "0x" or self.input_data == ""

    @property
    def selector(self) -> str | None:
        if len(self.input_data) >= 10:
            return self.input_data[:10]
        return None


class MempoolProvider(ABC):
    @abstractmethod
    async def subscribe(self) -> AsyncIterator[PendingTransaction]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class Web3WebSocketProvider(MempoolProvider):
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.w3: AsyncWeb3 | None = None
        self._running = False

    async def _connect(self) -> None:
        self.w3 = AsyncWeb3(WebSocketProvider(self.ws_url))
        if not await self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to {self.ws_url}")
        logger.info("websocket_connected", url=self.ws_url)

    async def subscribe(self) -> AsyncIterator[PendingTransaction]:
        await self._connect()
        if not self.w3:
            raise RuntimeError("Not connected")

        self._running = True

        async for tx_hash in self.w3.eth.subscribe("pendingTransactions"):
            if not self._running:
                break

            try:
                tx = await self.w3.eth.get_transaction(tx_hash)
                yield PendingTransaction.from_tx_data(tx)
            except Exception as e:
                logger.debug("tx_fetch_failed", tx_hash=tx_hash.hex(), error=str(e))

    async def close(self) -> None:
        self._running = False
        if self.w3:
            await self.w3.provider.disconnect()
            logger.info("websocket_disconnected")


class BloxrouteProvider(MempoolProvider):
    def __init__(self, ws_url: str, auth_header: str):
        self.ws_url = ws_url
        self.auth_header = auth_header
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            self.ws_url,
            headers={"Authorization": self.auth_header},
        )

        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "subscribe",
            "params": ["newTxs", {"include": ["tx_hash", "tx_contents"]}],
        }
        await self._ws.send_json(subscribe_msg)

        response = await self._ws.receive_json()
        if "error" in response:
            raise ConnectionError(f"Subscription failed: {response['error']}")

        logger.info("bloxroute_connected")

    async def subscribe(self) -> AsyncIterator[PendingTransaction]:
        await self._connect()
        if not self._ws:
            raise RuntimeError("Not connected")

        self._running = True

        async for msg in self._ws:
            if not self._running:
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if "params" in data and "result" in data["params"]:
                        tx_data = data["params"]["result"].get("txContents", {})
                        if tx_data:
                            yield self._parse_bloxroute_tx(tx_data)
                except Exception as e:
                    logger.debug("bloxroute_parse_error", error=str(e))

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

    def _parse_bloxroute_tx(self, tx: dict[str, Any]) -> PendingTransaction:
        return PendingTransaction(
            hash=tx.get("hash", ""),
            from_address=tx.get("from", ""),
            to_address=tx.get("to"),
            value=int(tx.get("value", "0x0"), 16),
            gas=int(tx.get("gas", "0x0"), 16),
            gas_price=int(tx.get("gasPrice", "0x0"), 16),
            max_fee_per_gas=int(tx["maxFeePerGas"], 16) if tx.get("maxFeePerGas") else None,
            max_priority_fee_per_gas=int(tx["maxPriorityFeePerGas"], 16) if tx.get("maxPriorityFeePerGas") else None,
            input_data=tx.get("input", "0x"),
            nonce=int(tx.get("nonce", "0x0"), 16),
            chain_id=int(tx["chainId"], 16) if tx.get("chainId") else None,
        )

    async def close(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        logger.info("bloxroute_disconnected")


class AlchemyProvider(MempoolProvider):
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False

    async def _connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(self.ws_url)

        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["alchemy_pendingTransactions", {"toAddress": [], "hashesOnly": False}],
        }
        await self._ws.send_json(subscribe_msg)

        response = await self._ws.receive_json()
        if "error" in response:
            raise ConnectionError(f"Subscription failed: {response['error']}")

        logger.info("alchemy_connected")

    async def subscribe(self) -> AsyncIterator[PendingTransaction]:
        await self._connect()
        if not self._ws:
            raise RuntimeError("Not connected")

        self._running = True

        async for msg in self._ws:
            if not self._running:
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if "params" in data and "result" in data["params"]:
                        tx_data = data["params"]["result"]
                        yield self._parse_alchemy_tx(tx_data)
                except Exception as e:
                    logger.debug("alchemy_parse_error", error=str(e))

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

    def _parse_alchemy_tx(self, tx: dict[str, Any]) -> PendingTransaction:
        return PendingTransaction(
            hash=tx.get("hash", ""),
            from_address=tx.get("from", ""),
            to_address=tx.get("to"),
            value=int(tx.get("value", "0x0"), 16),
            gas=int(tx.get("gas", "0x0"), 16),
            gas_price=int(tx.get("gasPrice", "0x0"), 16),
            max_fee_per_gas=int(tx["maxFeePerGas"], 16) if tx.get("maxFeePerGas") else None,
            max_priority_fee_per_gas=int(tx["maxPriorityFeePerGas"], 16) if tx.get("maxPriorityFeePerGas") else None,
            input_data=tx.get("input", "0x"),
            nonce=int(tx.get("nonce", "0x0"), 16),
            chain_id=int(tx["chainId"], 16) if tx.get("chainId") else None,
        )

    async def close(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        logger.info("alchemy_disconnected")


TransactionCallback = Callable[[PendingTransaction], None]


class MempoolListener:
    def __init__(
        self,
        provider: MempoolProvider,
        buffer_size: int = 10000,
    ):
        self.provider = provider
        self.buffer_size = buffer_size
        self._queue: asyncio.Queue[PendingTransaction] = asyncio.Queue(maxsize=buffer_size)
        self._callbacks: list[TransactionCallback] = []
        self._running = False
        self._listen_task: asyncio.Task | None = None
        self._stats = {"received": 0, "processed": 0, "dropped": 0}

    def add_callback(self, callback: TransactionCallback) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("mempool_listener_started")

    async def stop(self) -> None:
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        await self.provider.close()
        logger.info("mempool_listener_stopped", stats=self._stats)

    async def _listen_loop(self) -> None:
        try:
            async for tx in self.provider.subscribe():
                if not self._running:
                    break

                self._stats["received"] += 1

                try:
                    self._queue.put_nowait(tx)
                    self._stats["processed"] += 1

                    for callback in self._callbacks:
                        try:
                            callback(tx)
                        except Exception as e:
                            logger.error("callback_error", error=str(e))

                except asyncio.QueueFull:
                    self._stats["dropped"] += 1

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("listen_loop_error", error=str(e))

    async def get_transaction(self, timeout: float = 1.0) -> PendingTransaction | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    async def __aenter__(self) -> MempoolListener:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

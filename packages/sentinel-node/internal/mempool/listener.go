package mempool

import (
	"context"
	"math/big"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/rs/zerolog"

	ptypes "github.com/sentinel-protocol/sentinel-node/pkg/types"
)

type TransactionHandler func(*ptypes.PendingTransaction)

type Listener struct {
	client     *ethclient.Client
	wsClient   *ethclient.Client
	handlers   []TransactionHandler
	txChan     chan *ptypes.PendingTransaction
	bufferSize int
	running    bool
	mu         sync.RWMutex
	wg         sync.WaitGroup
	logger     zerolog.Logger

	stats struct {
		received  uint64
		processed uint64
		dropped   uint64
	}
}

type ListenerConfig struct {
	RPCURL     string
	WSURL      string
	BufferSize int
	Logger     zerolog.Logger
}

func NewListener(cfg ListenerConfig) (*Listener, error) {
	client, err := ethclient.Dial(cfg.RPCURL)
	if err != nil {
		return nil, err
	}

	var wsClient *ethclient.Client
	if cfg.WSURL != "" {
		wsClient, err = ethclient.Dial(cfg.WSURL)
		if err != nil {
			client.Close()
			return nil, err
		}
	}

	bufferSize := cfg.BufferSize
	if bufferSize == 0 {
		bufferSize = 10000
	}

	return &Listener{
		client:     client,
		wsClient:   wsClient,
		handlers:   make([]TransactionHandler, 0),
		txChan:     make(chan *ptypes.PendingTransaction, bufferSize),
		bufferSize: bufferSize,
		logger:     cfg.Logger,
	}, nil
}

func (l *Listener) AddHandler(handler TransactionHandler) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.handlers = append(l.handlers, handler)
}

func (l *Listener) Start(ctx context.Context) error {
	l.mu.Lock()
	if l.running {
		l.mu.Unlock()
		return nil
	}
	l.running = true
	l.mu.Unlock()

	l.wg.Add(2)
	go l.listenLoop(ctx)
	go l.processLoop(ctx)

	l.logger.Info().Msg("Mempool listener started")
	return nil
}

func (l *Listener) Stop() {
	l.mu.Lock()
	l.running = false
	l.mu.Unlock()

	l.wg.Wait()

	if l.client != nil {
		l.client.Close()
	}
	if l.wsClient != nil {
		l.wsClient.Close()
	}

	l.logger.Info().
		Uint64("received", l.stats.received).
		Uint64("processed", l.stats.processed).
		Uint64("dropped", l.stats.dropped).
		Msg("Mempool listener stopped")
}

func (l *Listener) listenLoop(ctx context.Context) {
	defer l.wg.Done()

	client := l.wsClient
	if client == nil {
		client = l.client
	}

	pendingTxChan := make(chan common.Hash, l.bufferSize)

	sub, err := client.Client().EthSubscribe(ctx, pendingTxChan, "newPendingTransactions")
	if err != nil {
		l.logger.Error().Err(err).Msg("Failed to subscribe to pending transactions")
		return
	}
	defer sub.Unsubscribe()

	l.logger.Info().Msg("Subscribed to pending transactions")

	for {
		select {
		case <-ctx.Done():
			return
		case err := <-sub.Err():
			l.logger.Error().Err(err).Msg("Subscription error")
			return
		case txHash := <-pendingTxChan:
			l.mu.RLock()
			running := l.running
			l.mu.RUnlock()
			if !running {
				return
			}

			l.stats.received++

			go l.fetchAndEnqueue(ctx, txHash)
		}
	}
}

func (l *Listener) fetchAndEnqueue(ctx context.Context, txHash common.Hash) {
	tx, isPending, err := l.client.TransactionByHash(ctx, txHash)
	if err != nil || !isPending {
		return
	}

	pendingTx := l.convertTransaction(tx, txHash)

	select {
	case l.txChan <- pendingTx:
	default:
		l.stats.dropped++
	}
}

func (l *Listener) processLoop(ctx context.Context) {
	defer l.wg.Done()

	for {
		select {
		case <-ctx.Done():
			return
		case tx := <-l.txChan:
			l.mu.RLock()
			running := l.running
			handlers := make([]TransactionHandler, len(l.handlers))
			copy(handlers, l.handlers)
			l.mu.RUnlock()

			if !running {
				return
			}

			l.stats.processed++

			for _, handler := range handlers {
				handler(tx)
			}
		}
	}
}

func (l *Listener) convertTransaction(tx *types.Transaction, hash common.Hash) *ptypes.PendingTransaction {
	var to *common.Address
	if tx.To() != nil {
		addr := *tx.To()
		to = &addr
	}

	msg, err := types.Sender(types.LatestSignerForChainID(tx.ChainId()), tx)
	from := common.Address{}
	if err == nil {
		from = msg
	}

	return &ptypes.PendingTransaction{
		Hash:                 hash,
		From:                 from,
		To:                   to,
		Value:                tx.Value(),
		Gas:                  tx.Gas(),
		GasPrice:             tx.GasPrice(),
		MaxFeePerGas:         tx.GasFeeCap(),
		MaxPriorityFeePerGas: tx.GasTipCap(),
		Input:                tx.Data(),
		Nonce:                tx.Nonce(),
		ChainID:              tx.ChainId(),
		ReceivedAt:           time.Now(),
	}
}

func (l *Listener) GetTransaction(ctx context.Context, timeout time.Duration) (*ptypes.PendingTransaction, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case tx := <-l.txChan:
		return tx, nil
	case <-time.After(timeout):
		return nil, nil
	}
}

func (l *Listener) GetStats() (received, processed, dropped uint64) {
	return l.stats.received, l.stats.processed, l.stats.dropped
}

func (l *Listener) SimulateTransaction(ctx context.Context, tx *ptypes.PendingTransaction) ([]byte, error) {
	var to common.Address
	if tx.To != nil {
		to = *tx.To
	}

	msg := ethereum.CallMsg{
		From:       tx.From,
		To:         &to,
		Gas:        tx.Gas,
		GasPrice:   tx.GasPrice,
		GasFeeCap:  tx.MaxFeePerGas,
		GasTipCap:  tx.MaxPriorityFeePerGas,
		Value:      tx.Value,
		Data:       tx.Input,
	}

	result, err := l.client.CallContract(ctx, msg, nil)
	if err != nil {
		return nil, err
	}

	return result, nil
}

func (l *Listener) GetGasPrice(ctx context.Context) (*big.Int, error) {
	return l.client.SuggestGasPrice(ctx)
}

func (l *Listener) GetNonce(ctx context.Context, address common.Address) (uint64, error) {
	return l.client.PendingNonceAt(ctx, address)
}

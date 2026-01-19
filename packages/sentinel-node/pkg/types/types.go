package types

import (
	"math/big"
	"time"

	"github.com/ethereum/go-ethereum/common"
)

type PendingTransaction struct {
	Hash                 common.Hash    `json:"hash"`
	From                 common.Address `json:"from"`
	To                   *common.Address `json:"to,omitempty"`
	Value                *big.Int       `json:"value"`
	Gas                  uint64         `json:"gas"`
	GasPrice             *big.Int       `json:"gasPrice"`
	MaxFeePerGas         *big.Int       `json:"maxFeePerGas,omitempty"`
	MaxPriorityFeePerGas *big.Int       `json:"maxPriorityFeePerGas,omitempty"`
	Input                []byte         `json:"input"`
	Nonce                uint64         `json:"nonce"`
	ChainID              *big.Int       `json:"chainId,omitempty"`
	ReceivedAt           time.Time      `json:"receivedAt"`
}

func (tx *PendingTransaction) IsContractInteraction() bool {
	return tx.To != nil && len(tx.Input) > 0
}

func (tx *PendingTransaction) IsContractCreation() bool {
	return tx.To == nil && len(tx.Input) > 0
}

func (tx *PendingTransaction) IsSimpleTransfer() bool {
	return len(tx.Input) == 0 || (len(tx.Input) == 1 && tx.Input[0] == 0)
}

func (tx *PendingTransaction) Selector() []byte {
	if len(tx.Input) >= 4 {
		return tx.Input[:4]
	}
	return nil
}

type InferenceResult struct {
	TxHash         common.Hash `json:"txHash"`
	IsSuspicious   bool        `json:"isSuspicious"`
	AnomalyScore   float64     `json:"anomalyScore"`
	Confidence     float64     `json:"confidence"`
	RiskLevel      string      `json:"riskLevel"`
	RiskIndicators []string    `json:"riskIndicators"`
	Recommendation string      `json:"recommendation"`
	LatencyMs      float64     `json:"latencyMs"`
}

type PauseRequest struct {
	TargetProtocol common.Address `json:"targetProtocol"`
	EvidenceHash   common.Hash    `json:"evidenceHash"`
	Timestamp      time.Time      `json:"timestamp"`
	Signers        []common.Address `json:"signers"`
}

type SignedPauseRequest struct {
	Request   PauseRequest `json:"request"`
	Signature []byte       `json:"signature"`
	Signer    common.Address `json:"signer"`
}

type AggregatedPauseRequest struct {
	Request             PauseRequest   `json:"request"`
	AggregatedSignature []byte         `json:"aggregatedSignature"`
	Signers             []common.Address `json:"signers"`
}

type NodeInfo struct {
	Address      common.Address `json:"address"`
	PeerID       string         `json:"peerId"`
	BLSPublicKey []byte         `json:"blsPublicKey"`
	Stake        *big.Int       `json:"stake"`
	IsActive     bool           `json:"isActive"`
}

type ProtocolInfo struct {
	Address     common.Address `json:"address"`
	PauseTarget common.Address `json:"pauseTarget"`
	TVL         *big.Int       `json:"tvl"`
	Stake       *big.Int       `json:"stake"`
	IsActive    bool           `json:"isActive"`
}

type NodeStats struct {
	TransactionsAnalyzed uint64        `json:"transactionsAnalyzed"`
	SuspiciousDetected   uint64        `json:"suspiciousDetected"`
	PauseRequestsCreated uint64        `json:"pauseRequestsCreated"`
	PauseRequestsSigned  uint64        `json:"pauseRequestsSigned"`
	AverageLatencyMs     float64       `json:"averageLatencyMs"`
	Uptime               time.Duration `json:"uptime"`
}

type AlertLevel string

const (
	AlertLevelLow      AlertLevel = "low"
	AlertLevelMedium   AlertLevel = "medium"
	AlertLevelHigh     AlertLevel = "high"
	AlertLevelCritical AlertLevel = "critical"
)

type Alert struct {
	ID             string         `json:"id"`
	Level          AlertLevel     `json:"level"`
	TxHash         common.Hash    `json:"txHash"`
	TargetProtocol common.Address `json:"targetProtocol,omitempty"`
	Message        string         `json:"message"`
	Timestamp      time.Time      `json:"timestamp"`
	Result         *InferenceResult `json:"result,omitempty"`
}

package inference

import (
	"context"
	"math/big"
	"testing"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/rs/zerolog"

	"github.com/sentinel-protocol/sentinel-node/pkg/types"
)

func TestNewBridge(t *testing.T) {
	logger := zerolog.Nop()

	bridge, err := NewBridge(BridgeConfig{
		Address:          "", // No server for test
		Timeout:          300 * time.Millisecond,
		AnomalyThreshold: 0.65,
		Logger:           logger,
	})

	if err != nil {
		t.Fatalf("NewBridge failed: %v", err)
	}

	if bridge == nil {
		t.Error("Bridge should not be nil")
	}
}

func TestBridge_Defaults(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	if bridge.timeout != 300*time.Millisecond {
		t.Errorf("Expected default timeout 300ms, got %v", bridge.timeout)
	}

	if bridge.maxRetries != 3 {
		t.Errorf("Expected default maxRetries 3, got %d", bridge.maxRetries)
	}

	if bridge.anomalyThreshold != 0.65 {
		t.Errorf("Expected default threshold 0.65, got %f", bridge.anomalyThreshold)
	}
}

func TestBridge_IsConnected(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	// Should not be connected without a server
	if bridge.IsConnected() {
		t.Error("Should not be connected without a server")
	}
}

func TestBridge_QuickFilter_SimpleTransfer(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	// Simple ETH transfer
	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(1e18),
		Gas:   21000,
		Input: []byte{}, // No data
	}

	// Simple transfers should not require analysis
	shouldAnalyze := bridge.QuickFilter(tx)
	if shouldAnalyze {
		t.Error("Simple transfer should not require analysis")
	}
}

func TestBridge_QuickFilter_ContractInteraction(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	// Contract interaction with high gas
	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(0),
		Gas:   500000,
		Input: []byte{0x5c, 0xff, 0xe9, 0xde}, // flashLoan selector
	}

	// Contract interactions with high gas should require analysis
	shouldAnalyze := bridge.QuickFilter(tx)
	if !shouldAnalyze {
		t.Error("Contract interaction should require analysis")
	}
}

func TestBridge_QuickFilter_LowGas(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	// Low gas contract call
	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(0),
		Gas:   50000, // Below 100k threshold
		Input: []byte{0x5c, 0xff, 0xe9, 0xde},
	}

	// Low gas should not require analysis
	shouldAnalyze := bridge.QuickFilter(tx)
	if shouldAnalyze {
		t.Error("Low gas transaction should not require analysis")
	}
}

func TestBridge_Analyze_Fallback(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(1e18),
		Gas:   500000,
		Input: []byte{0x5c, 0xff, 0xe9, 0xde}, // flashLoan
	}

	ctx := context.Background()
	result, err := bridge.Analyze(ctx, tx)
	if err != nil {
		t.Fatalf("Analyze failed: %v", err)
	}

	if result == nil {
		t.Fatal("Result should not be nil")
	}

	// Should have fallback indicator
	hasFallback := false
	for _, indicator := range result.RiskIndicators {
		if indicator == "fallback_analysis" {
			hasFallback = true
			break
		}
	}
	if !hasFallback {
		t.Error("Should have fallback_analysis indicator when not connected")
	}
}

func TestBridge_Analyze_SimpleTransfer(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(1e18),
		Gas:   21000,
		Input: []byte{},
	}

	ctx := context.Background()
	result, err := bridge.Analyze(ctx, tx)
	if err != nil {
		t.Fatalf("Analyze failed: %v", err)
	}

	if result.IsSuspicious {
		t.Error("Simple transfer should not be suspicious")
	}

	if result.RiskLevel != "low" {
		t.Errorf("Expected risk level 'low', got '%s'", result.RiskLevel)
	}
}

func TestBridge_Analyze_FlashLoan(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger:           logger,
		AnomalyThreshold: 0.4, // Lower threshold to catch flash loans
	})

	tx := &types.PendingTransaction{
		Hash:  common.HexToHash("0x1234"),
		From:  common.HexToAddress("0x1"),
		To:    ptrAddr(common.HexToAddress("0x2")),
		Value: big.NewInt(0),
		Gas:   2000000,
		Input: []byte{0x5c, 0xff, 0xe9, 0xde}, // flashLoan selector
	}

	ctx := context.Background()
	result, err := bridge.Analyze(ctx, tx)
	if err != nil {
		t.Fatalf("Analyze failed: %v", err)
	}

	// Should detect flash loan
	hasFlashLoan := false
	for _, indicator := range result.RiskIndicators {
		if indicator == "flash_loan_detected" {
			hasFlashLoan = true
			break
		}
	}
	if !hasFlashLoan {
		t.Error("Should detect flash loan")
	}
}

func TestBridge_SetThreshold(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	bridge.SetThreshold(0.5)
	if bridge.GetThreshold() != 0.5 {
		t.Errorf("Expected threshold 0.5, got %f", bridge.GetThreshold())
	}
}

func TestBridge_CircuitBreaker(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	isOpen, failures, _ := bridge.GetCircuitBreakerStatus()
	if isOpen {
		t.Error("Circuit breaker should not be open initially")
	}
	if failures != 0 {
		t.Errorf("Expected 0 failures, got %d", failures)
	}
}

func TestBridge_AnalyzeBatch(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	txs := []*types.PendingTransaction{
		{
			Hash:  common.HexToHash("0x1"),
			From:  common.HexToAddress("0x1"),
			To:    ptrAddr(common.HexToAddress("0x2")),
			Value: big.NewInt(1e18),
			Gas:   21000,
			Input: []byte{},
		},
		{
			Hash:  common.HexToHash("0x2"),
			From:  common.HexToAddress("0x3"),
			To:    ptrAddr(common.HexToAddress("0x4")),
			Value: big.NewInt(0),
			Gas:   500000,
			Input: []byte{0x5c, 0xff, 0xe9, 0xde},
		},
	}

	ctx := context.Background()
	results, err := bridge.AnalyzeBatch(ctx, txs)
	if err != nil {
		t.Fatalf("AnalyzeBatch failed: %v", err)
	}

	if len(results) != len(txs) {
		t.Errorf("Expected %d results, got %d", len(txs), len(results))
	}
}

func TestBridge_Close(t *testing.T) {
	logger := zerolog.Nop()

	bridge, _ := NewBridge(BridgeConfig{
		Logger: logger,
	})

	err := bridge.Close()
	if err != nil {
		t.Fatalf("Close failed: %v", err)
	}
}

// Helper to create pointer to address
func ptrAddr(addr common.Address) *common.Address {
	return &addr
}

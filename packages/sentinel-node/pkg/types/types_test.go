package types

import (
	"math/big"
	"testing"
	"time"

	"github.com/ethereum/go-ethereum/common"
)

func TestPendingTransaction_IsContractInteraction(t *testing.T) {
	tests := []struct {
		name     string
		tx       *PendingTransaction
		expected bool
	}{
		{
			name: "contract interaction",
			tx: &PendingTransaction{
				To:    ptrAddr(common.HexToAddress("0x1")),
				Input: []byte{0x5c, 0xff, 0xe9, 0xde},
			},
			expected: true,
		},
		{
			name: "simple transfer",
			tx: &PendingTransaction{
				To:    ptrAddr(common.HexToAddress("0x1")),
				Input: []byte{},
			},
			expected: false,
		},
		{
			name: "contract creation",
			tx: &PendingTransaction{
				To:    nil,
				Input: []byte{0x60, 0x80, 0x60, 0x40},
			},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.tx.IsContractInteraction()
			if result != tt.expected {
				t.Errorf("Expected %v, got %v", tt.expected, result)
			}
		})
	}
}

func TestPendingTransaction_IsContractCreation(t *testing.T) {
	tests := []struct {
		name     string
		tx       *PendingTransaction
		expected bool
	}{
		{
			name: "contract creation",
			tx: &PendingTransaction{
				To:    nil,
				Input: []byte{0x60, 0x80, 0x60, 0x40},
			},
			expected: true,
		},
		{
			name: "simple transfer",
			tx: &PendingTransaction{
				To:    ptrAddr(common.HexToAddress("0x1")),
				Input: []byte{},
			},
			expected: false,
		},
		{
			name: "contract interaction",
			tx: &PendingTransaction{
				To:    ptrAddr(common.HexToAddress("0x1")),
				Input: []byte{0x5c, 0xff, 0xe9, 0xde},
			},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.tx.IsContractCreation()
			if result != tt.expected {
				t.Errorf("Expected %v, got %v", tt.expected, result)
			}
		})
	}
}

func TestPendingTransaction_IsSimpleTransfer(t *testing.T) {
	tests := []struct {
		name     string
		tx       *PendingTransaction
		expected bool
	}{
		{
			name: "simple transfer",
			tx: &PendingTransaction{
				Input: []byte{},
			},
			expected: true,
		},
		{
			name: "simple transfer with zero byte",
			tx: &PendingTransaction{
				Input: []byte{0x00},
			},
			expected: true,
		},
		{
			name: "contract interaction",
			tx: &PendingTransaction{
				Input: []byte{0x5c, 0xff, 0xe9, 0xde},
			},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.tx.IsSimpleTransfer()
			if result != tt.expected {
				t.Errorf("Expected %v, got %v", tt.expected, result)
			}
		})
	}
}

func TestPendingTransaction_Selector(t *testing.T) {
	tests := []struct {
		name     string
		input    []byte
		expected []byte
	}{
		{
			name:     "valid selector",
			input:    []byte{0x5c, 0xff, 0xe9, 0xde, 0x00, 0x00},
			expected: []byte{0x5c, 0xff, 0xe9, 0xde},
		},
		{
			name:     "exactly 4 bytes",
			input:    []byte{0x5c, 0xff, 0xe9, 0xde},
			expected: []byte{0x5c, 0xff, 0xe9, 0xde},
		},
		{
			name:     "too short",
			input:    []byte{0x5c, 0xff},
			expected: nil,
		},
		{
			name:     "empty",
			input:    []byte{},
			expected: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tx := &PendingTransaction{Input: tt.input}
			result := tx.Selector()

			if tt.expected == nil {
				if result != nil {
					t.Errorf("Expected nil, got %v", result)
				}
			} else {
				if len(result) != len(tt.expected) {
					t.Errorf("Expected %v, got %v", tt.expected, result)
				}
				for i := range result {
					if result[i] != tt.expected[i] {
						t.Errorf("Expected %v, got %v", tt.expected, result)
						break
					}
				}
			}
		})
	}
}

func TestInferenceResult(t *testing.T) {
	result := InferenceResult{
		TxHash:         common.HexToHash("0x1234"),
		IsSuspicious:   true,
		AnomalyScore:   0.85,
		Confidence:     0.9,
		RiskLevel:      "high",
		RiskIndicators: []string{"flash_loan_detected", "high_gas"},
		Recommendation: "block",
		LatencyMs:      25.5,
	}

	if !result.IsSuspicious {
		t.Error("Should be suspicious")
	}

	if result.RiskLevel != "high" {
		t.Errorf("Expected 'high', got '%s'", result.RiskLevel)
	}

	if len(result.RiskIndicators) != 2 {
		t.Errorf("Expected 2 indicators, got %d", len(result.RiskIndicators))
	}
}

func TestPauseRequest(t *testing.T) {
	request := PauseRequest{
		TargetProtocol: common.HexToAddress("0x1"),
		EvidenceHash:   common.HexToHash("0x2"),
		Timestamp:      time.Now(),
		Signers:        []common.Address{common.HexToAddress("0x3")},
	}

	if request.TargetProtocol == (common.Address{}) {
		t.Error("TargetProtocol should not be zero")
	}

	if len(request.Signers) != 1 {
		t.Errorf("Expected 1 signer, got %d", len(request.Signers))
	}
}

func TestSignedPauseRequest(t *testing.T) {
	request := SignedPauseRequest{
		Request: PauseRequest{
			TargetProtocol: common.HexToAddress("0x1"),
			EvidenceHash:   common.HexToHash("0x2"),
			Timestamp:      time.Now(),
		},
		Signature: []byte{0x01, 0x02, 0x03},
		Signer:    common.HexToAddress("0x3"),
	}

	if len(request.Signature) == 0 {
		t.Error("Signature should not be empty")
	}

	if request.Signer == (common.Address{}) {
		t.Error("Signer should not be zero")
	}
}

func TestAggregatedPauseRequest(t *testing.T) {
	request := AggregatedPauseRequest{
		Request: PauseRequest{
			TargetProtocol: common.HexToAddress("0x1"),
		},
		AggregatedSignature: []byte{0x01, 0x02, 0x03},
		Signers: []common.Address{
			common.HexToAddress("0x2"),
			common.HexToAddress("0x3"),
		},
	}

	if len(request.Signers) != 2 {
		t.Errorf("Expected 2 signers, got %d", len(request.Signers))
	}
}

func TestNodeInfo(t *testing.T) {
	stake, _ := new(big.Int).SetString("10000000000000000000000", 10) // 10000 * 1e18
	info := NodeInfo{
		Address:      common.HexToAddress("0x1"),
		PeerID:       "QmTest123",
		BLSPublicKey: []byte{0x01, 0x02, 0x03},
		Stake:        stake,
		IsActive:     true,
	}

	if !info.IsActive {
		t.Error("Node should be active")
	}

	if info.PeerID == "" {
		t.Error("PeerID should not be empty")
	}
}

func TestProtocolInfo(t *testing.T) {
	tvl, _ := new(big.Int).SetString("1000000000000", 10)    // 1000000 * 1e6
	stake, _ := new(big.Int).SetString("25000000000000000000000", 10) // 25000 * 1e18
	info := ProtocolInfo{
		Address:     common.HexToAddress("0x1"),
		PauseTarget: common.HexToAddress("0x2"),
		TVL:         tvl,
		Stake:       stake,
		IsActive:    true,
	}

	if !info.IsActive {
		t.Error("Protocol should be active")
	}

	if info.PauseTarget == (common.Address{}) {
		t.Error("PauseTarget should not be zero")
	}
}

func TestNodeStats(t *testing.T) {
	stats := NodeStats{
		TransactionsAnalyzed: 1000,
		SuspiciousDetected:   50,
		PauseRequestsCreated: 5,
		PauseRequestsSigned:  10,
		AverageLatencyMs:     25.5,
		Uptime:               24 * time.Hour,
	}

	if stats.TransactionsAnalyzed != 1000 {
		t.Errorf("Expected 1000 transactions, got %d", stats.TransactionsAnalyzed)
	}

	if stats.Uptime != 24*time.Hour {
		t.Errorf("Expected 24h uptime, got %v", stats.Uptime)
	}
}

func TestAlertLevel(t *testing.T) {
	if AlertLevelLow != "low" {
		t.Errorf("Expected 'low', got '%s'", AlertLevelLow)
	}
	if AlertLevelMedium != "medium" {
		t.Errorf("Expected 'medium', got '%s'", AlertLevelMedium)
	}
	if AlertLevelHigh != "high" {
		t.Errorf("Expected 'high', got '%s'", AlertLevelHigh)
	}
	if AlertLevelCritical != "critical" {
		t.Errorf("Expected 'critical', got '%s'", AlertLevelCritical)
	}
}

func TestAlert(t *testing.T) {
	alert := Alert{
		ID:             "alert-123",
		Level:          AlertLevelHigh,
		TxHash:         common.HexToHash("0x1234"),
		TargetProtocol: common.HexToAddress("0x5678"),
		Message:        "Suspicious transaction detected",
		Timestamp:      time.Now(),
		Result: &InferenceResult{
			IsSuspicious: true,
			AnomalyScore: 0.85,
		},
	}

	if alert.Level != AlertLevelHigh {
		t.Errorf("Expected 'high', got '%s'", alert.Level)
	}

	if alert.Result == nil {
		t.Error("Result should not be nil")
	}
}

// Helper to create pointer to address
func ptrAddr(addr common.Address) *common.Address {
	return &addr
}

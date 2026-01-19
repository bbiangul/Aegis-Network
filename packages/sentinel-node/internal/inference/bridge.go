package inference

import (
	"context"
	"encoding/hex"
	"fmt"
	"math/big"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/rs/zerolog"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "github.com/sentinel-protocol/sentinel-node/pkg/proto"
	"github.com/sentinel-protocol/sentinel-node/pkg/types"
)

type BridgeConfig struct {
	Address          string
	Timeout          time.Duration
	MaxRetries       int
	AnomalyThreshold float64
	Logger           zerolog.Logger
}

type Bridge struct {
	conn             *grpc.ClientConn
	client           pb.SentinelInferenceClient
	timeout          time.Duration
	maxRetries       int
	anomalyThreshold float64
	logger           zerolog.Logger
	connected        bool

	// FIX: Add fields for error recovery
	address             string
	mu                  sync.RWMutex
	consecutiveFailures int
	circuitOpen         bool
	circuitOpenUntil    time.Time
	lastHealthCheck     time.Time
	healthCheckInterval time.Duration
	reconnectChan       chan struct{}
	stopChan            chan struct{}
}

// FIX: Circuit breaker constants
const (
	maxConsecutiveFailures = 5
	circuitOpenDuration    = 1 * time.Minute
	defaultHealthInterval  = 30 * time.Second
)

func NewBridge(cfg BridgeConfig) (*Bridge, error) {
	timeout := cfg.Timeout
	if timeout == 0 {
		timeout = 300 * time.Millisecond
	}

	maxRetries := cfg.MaxRetries
	if maxRetries == 0 {
		maxRetries = 3
	}

	threshold := cfg.AnomalyThreshold
	if threshold == 0 {
		threshold = 0.65
	}

	bridge := &Bridge{
		timeout:             timeout,
		maxRetries:          maxRetries,
		anomalyThreshold:    threshold,
		logger:              cfg.Logger,
		connected:           false,
		address:             cfg.Address,
		healthCheckInterval: defaultHealthInterval,
		reconnectChan:       make(chan struct{}, 1),
		stopChan:            make(chan struct{}),
	}

	// Try to connect to the gRPC server
	if cfg.Address != "" {
		bridge.attemptConnect()
	}

	return bridge, nil
}

// FIX: Start background health monitoring and reconnection
func (b *Bridge) Start(ctx context.Context) {
	go b.healthCheckLoop(ctx)
	go b.reconnectLoop(ctx)
}

// FIX: Attempt to connect to the inference server
func (b *Bridge) attemptConnect() bool {
	if b.address == "" {
		return false
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	conn, err := grpc.DialContext(
		ctx,
		b.address,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		b.logger.Warn().Err(err).Str("address", b.address).Msg("failed to connect to inference server, using fallback")
		return false
	}

	b.mu.Lock()
	// Close old connection if exists
	if b.conn != nil {
		b.conn.Close()
	}
	b.conn = conn
	b.client = pb.NewSentinelInferenceClient(conn)
	b.connected = true
	b.consecutiveFailures = 0
	b.circuitOpen = false
	b.mu.Unlock()

	b.logger.Info().Str("address", b.address).Msg("connected to inference server")
	return true
}

// FIX: Background health check loop
func (b *Bridge) healthCheckLoop(ctx context.Context) {
	ticker := time.NewTicker(b.healthCheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-b.stopChan:
			return
		case <-ticker.C:
			b.checkHealth(ctx)
		}
	}
}

// FIX: Check health and update connection state
func (b *Bridge) checkHealth(ctx context.Context) {
	b.mu.RLock()
	connected := b.connected
	client := b.client
	b.mu.RUnlock()

	if !connected || client == nil {
		return
	}

	healthCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	_, err := client.Health(healthCtx, &pb.HealthRequest{})
	if err != nil {
		b.logger.Warn().Err(err).Msg("health check failed, marking as disconnected")
		b.mu.Lock()
		b.connected = false
		b.mu.Unlock()
		b.triggerReconnect()
	} else {
		b.mu.Lock()
		b.lastHealthCheck = time.Now()
		b.mu.Unlock()
	}
}

// FIX: Background reconnection loop
func (b *Bridge) reconnectLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-b.stopChan:
			return
		case <-b.reconnectChan:
			b.mu.RLock()
			connected := b.connected
			b.mu.RUnlock()

			if !connected && b.address != "" {
				b.logger.Info().Msg("attempting to reconnect to inference server")
				if b.attemptConnect() {
					b.logger.Info().Msg("successfully reconnected to inference server")
				} else {
					// Retry after a delay
					time.AfterFunc(10*time.Second, func() {
						b.triggerReconnect()
					})
				}
			}
		}
	}
}

// FIX: Trigger a reconnection attempt (non-blocking)
func (b *Bridge) triggerReconnect() {
	select {
	case b.reconnectChan <- struct{}{}:
	default:
		// Channel full, reconnect already pending
	}
}

func (b *Bridge) Close() error {
	// FIX: Signal background goroutines to stop
	close(b.stopChan)

	b.mu.Lock()
	defer b.mu.Unlock()
	if b.conn != nil {
		return b.conn.Close()
	}
	return nil
}

func (b *Bridge) IsConnected() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.connected
}

// FIX: Check if circuit breaker is open
func (b *Bridge) isCircuitOpen() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.circuitOpen && time.Now().Before(b.circuitOpenUntil)
}

// FIX: Record a failure and potentially open circuit breaker
func (b *Bridge) recordFailure() {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.consecutiveFailures++
	if b.consecutiveFailures >= maxConsecutiveFailures {
		b.circuitOpen = true
		b.circuitOpenUntil = time.Now().Add(circuitOpenDuration)
		b.connected = false
		b.logger.Warn().
			Int("failures", b.consecutiveFailures).
			Time("reopenAt", b.circuitOpenUntil).
			Msg("circuit breaker opened due to consecutive failures")
	}
}

// FIX: Record a success and reset circuit breaker
func (b *Bridge) recordSuccess() {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.consecutiveFailures > 0 {
		b.logger.Debug().Int("previousFailures", b.consecutiveFailures).Msg("inference call succeeded, resetting failure count")
	}
	b.consecutiveFailures = 0
	b.circuitOpen = false
}

func (b *Bridge) Analyze(ctx context.Context, tx *types.PendingTransaction) (*types.InferenceResult, error) {
	start := time.Now()

	ctx, cancel := context.WithTimeout(ctx, b.timeout)
	defer cancel()

	var result *types.InferenceResult
	var err error

	// FIX: Check circuit breaker first
	if b.isCircuitOpen() {
		b.logger.Debug().Str("txHash", tx.Hash.Hex()).Msg("circuit breaker open, using fallback")
		result = b.fallbackAnalysis(tx, start)
		result.RiskIndicators = append(result.RiskIndicators, "circuit_breaker_open")
		result.LatencyMs = float64(time.Since(start).Milliseconds())
		return result, nil
	}

	// FIX: Thread-safe check for connection
	b.mu.RLock()
	connected := b.connected
	b.mu.RUnlock()

	// Try gRPC first if connected
	if connected {
		result, err = b.callInference(ctx, tx)
		if err != nil {
			b.logger.Warn().Err(err).Str("txHash", tx.Hash.Hex()).Msg("gRPC call failed, using fallback")
			// FIX: Record failure for circuit breaker
			b.recordFailure()
			// FIX: Trigger reconnection attempt
			b.triggerReconnect()
			result = b.fallbackAnalysis(tx, start)
		} else {
			// FIX: Record success
			b.recordSuccess()
		}
	} else {
		result = b.fallbackAnalysis(tx, start)
		// FIX: Trigger reconnection if not connected
		b.triggerReconnect()
	}

	result.LatencyMs = float64(time.Since(start).Milliseconds())
	return result, nil
}

func (b *Bridge) AnalyzeBatch(ctx context.Context, txs []*types.PendingTransaction) ([]*types.InferenceResult, error) {
	// FIX: Thread-safe check for connection and circuit breaker
	if b.isCircuitOpen() {
		// Circuit open, use individual fallback analysis
		results := make([]*types.InferenceResult, len(txs))
		for i, tx := range txs {
			result, _ := b.Analyze(ctx, tx)
			results[i] = result
		}
		return results, nil
	}

	b.mu.RLock()
	connected := b.connected
	b.mu.RUnlock()

	if connected {
		results, err := b.callBatchInference(ctx, txs)
		if err != nil {
			b.recordFailure()
			b.triggerReconnect()
			// Fallback to individual analysis
			results = make([]*types.InferenceResult, len(txs))
			for i, tx := range txs {
				result, _ := b.Analyze(ctx, tx)
				results[i] = result
			}
			return results, nil
		}
		b.recordSuccess()
		return results, nil
	}

	// Fallback to individual analysis
	results := make([]*types.InferenceResult, len(txs))
	for i, tx := range txs {
		result, _ := b.Analyze(ctx, tx)
		results[i] = result
	}
	return results, nil
}

func (b *Bridge) callInference(ctx context.Context, tx *types.PendingTransaction) (*types.InferenceResult, error) {
	if b.client == nil {
		return nil, fmt.Errorf("gRPC client not initialized")
	}

	// Convert transaction to gRPC request
	req := b.txToRequest(tx)

	// Call the inference server with retries
	var resp *pb.AnalyzeResponse
	var err error

	for attempt := 0; attempt < b.maxRetries; attempt++ {
		resp, err = b.client.Analyze(ctx, req)
		if err == nil {
			break
		}
		b.logger.Debug().Err(err).Int("attempt", attempt+1).Msg("inference call failed, retrying")
		time.Sleep(time.Duration(attempt+1) * 10 * time.Millisecond)
	}

	if err != nil {
		return nil, fmt.Errorf("inference call failed after %d attempts: %w", b.maxRetries, err)
	}

	// Convert response to InferenceResult
	return b.responseToResult(resp, tx.Hash), nil
}

func (b *Bridge) callBatchInference(ctx context.Context, txs []*types.PendingTransaction) ([]*types.InferenceResult, error) {
	if b.client == nil {
		return nil, fmt.Errorf("gRPC client not initialized")
	}

	// Build batch request
	requests := make([]*pb.AnalyzeRequest, len(txs))
	for i, tx := range txs {
		requests[i] = b.txToRequest(tx)
	}

	req := &pb.AnalyzeBatchRequest{
		Transactions: requests,
	}

	resp, err := b.client.AnalyzeBatch(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("batch inference call failed: %w", err)
	}

	// Convert responses
	results := make([]*types.InferenceResult, len(resp.Results))
	for i, r := range resp.Results {
		results[i] = b.responseToResult(r, txs[i].Hash)
	}

	return results, nil
}

func (b *Bridge) txToRequest(tx *types.PendingTransaction) *pb.AnalyzeRequest {
	req := &pb.AnalyzeRequest{
		TxHash:      tx.Hash.Hex(),
		FromAddress: tx.From.Hex(),
		Gas:         tx.Gas,
		Nonce:       tx.Nonce,
		InputData:   tx.Input,
	}

	if tx.To != nil {
		req.ToAddress = tx.To.Hex()
	}

	if tx.Value != nil {
		req.Value = tx.Value.String()
	}

	if tx.GasPrice != nil {
		req.GasPrice = tx.GasPrice.String()
	}

	if tx.ChainID != nil {
		req.ChainId = tx.ChainID.Uint64()
	}

	return req
}

func (b *Bridge) responseToResult(resp *pb.AnalyzeResponse, txHash common.Hash) *types.InferenceResult {
	// Map risk level
	riskLevel := "low"
	switch resp.RiskLevel {
	case pb.RiskLevel_RISK_SAFE:
		riskLevel = "safe"
	case pb.RiskLevel_RISK_LOW:
		riskLevel = "low"
	case pb.RiskLevel_RISK_MEDIUM:
		riskLevel = "medium"
	case pb.RiskLevel_RISK_HIGH:
		riskLevel = "high"
	case pb.RiskLevel_RISK_CRITICAL:
		riskLevel = "critical"
	}

	// Map recommendation
	recommendation := "allow"
	switch resp.Recommendation {
	case pb.Recommendation_RECOMMENDATION_ALLOW:
		recommendation = "allow"
	case pb.Recommendation_RECOMMENDATION_FLAG:
		recommendation = "flag"
	case pb.Recommendation_RECOMMENDATION_REVIEW:
		recommendation = "review"
	case pb.Recommendation_RECOMMENDATION_BLOCK:
		recommendation = "block"
	}

	return &types.InferenceResult{
		TxHash:         txHash,
		IsSuspicious:   resp.IsSuspicious,
		AnomalyScore:   resp.AnomalyScore,
		Confidence:     resp.Confidence,
		RiskLevel:      riskLevel,
		RiskIndicators: resp.RiskIndicators,
		Recommendation: recommendation,
		LatencyMs:      resp.LatencyMs,
	}
}

func (b *Bridge) Health(ctx context.Context) (*pb.HealthResponse, error) {
	b.mu.RLock()
	client := b.client
	b.mu.RUnlock()

	if client == nil {
		return nil, fmt.Errorf("gRPC client not initialized")
	}

	return client.Health(ctx, &pb.HealthRequest{})
}

func (b *Bridge) GetStats(ctx context.Context) (*pb.StatsResponse, error) {
	b.mu.RLock()
	client := b.client
	b.mu.RUnlock()

	if client == nil {
		return nil, fmt.Errorf("gRPC client not initialized")
	}

	return client.GetStats(ctx, &pb.StatsRequest{})
}

// FIX: Get circuit breaker status for monitoring
func (b *Bridge) GetCircuitBreakerStatus() (isOpen bool, failures int, reopenAt time.Time) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.circuitOpen, b.consecutiveFailures, b.circuitOpenUntil
}

func (b *Bridge) heuristicAnalysis(tx *types.PendingTransaction) *types.InferenceResult {
	riskIndicators := make([]string, 0)
	anomalyScore := 0.0

	if tx.IsSimpleTransfer() {
		return &types.InferenceResult{
			TxHash:         tx.Hash,
			IsSuspicious:   false,
			AnomalyScore:   0.0,
			Confidence:     0.99,
			RiskLevel:      "low",
			RiskIndicators: []string{},
			Recommendation: "allow",
		}
	}

	selector := tx.Selector()
	if selector != nil {
		selectorHex := hex.EncodeToString(selector)

		flashLoanSelectors := map[string]bool{
			"5cffe9de": true, // flashLoan
			"ab9c4b5d": true, // flashLoan (Aave v3)
			"c1a8a1f5": true, // flash
			"490e6cbc": true, // flash (Uniswap v3)
		}

		if flashLoanSelectors[selectorHex] {
			riskIndicators = append(riskIndicators, "flash_loan_detected")
			anomalyScore += 0.4
		}
	}

	if tx.Gas > 1_000_000 {
		riskIndicators = append(riskIndicators, "high_gas_limit")
		anomalyScore += 0.1
	}

	if tx.Value != nil && tx.Value.Cmp(big1ETH) >= 0 {
		riskIndicators = append(riskIndicators, "large_value_transfer")
		anomalyScore += 0.1
	}

	if tx.IsContractCreation() {
		riskIndicators = append(riskIndicators, "contract_creation")
		anomalyScore += 0.2
	}

	if len(tx.Input) > 10000 {
		riskIndicators = append(riskIndicators, "large_calldata")
		anomalyScore += 0.1
	}

	if anomalyScore > 1.0 {
		anomalyScore = 1.0
	}

	isSuspicious := anomalyScore >= b.anomalyThreshold
	riskLevel := "low"
	recommendation := "allow"

	if anomalyScore >= 0.8 {
		riskLevel = "critical"
		recommendation = "block"
	} else if anomalyScore >= 0.65 {
		riskLevel = "high"
		recommendation = "block"
	} else if anomalyScore >= 0.4 {
		riskLevel = "medium"
		recommendation = "flag"
	}

	confidence := 0.5 + (0.5 * (1.0 - anomalyScore))
	if isSuspicious {
		confidence = 0.5 + (0.5 * anomalyScore)
	}

	return &types.InferenceResult{
		TxHash:         tx.Hash,
		IsSuspicious:   isSuspicious,
		AnomalyScore:   anomalyScore,
		Confidence:     confidence,
		RiskLevel:      riskLevel,
		RiskIndicators: riskIndicators,
		Recommendation: recommendation,
	}
}

func (b *Bridge) fallbackAnalysis(tx *types.PendingTransaction, start time.Time) *types.InferenceResult {
	result := b.heuristicAnalysis(tx)
	result.LatencyMs = float64(time.Since(start).Milliseconds())
	result.RiskIndicators = append(result.RiskIndicators, "fallback_analysis")
	return result
}

func (b *Bridge) QuickFilter(tx *types.PendingTransaction) bool {
	if tx.IsSimpleTransfer() {
		return false
	}

	if tx.Gas < 100_000 {
		return false
	}

	return true
}

func (b *Bridge) SetThreshold(threshold float64) {
	b.anomalyThreshold = threshold
}

func (b *Bridge) GetThreshold() float64 {
	return b.anomalyThreshold
}

var big1ETH = func() *big.Int {
	v, _ := new(big.Int).SetString("1000000000000000000", 10)
	return v
}()

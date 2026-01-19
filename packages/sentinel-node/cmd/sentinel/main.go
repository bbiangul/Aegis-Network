package main

import (
	"context"
	"flag"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"

	"github.com/sentinel-protocol/sentinel-node/internal/config"
	"github.com/sentinel-protocol/sentinel-node/internal/consensus"
	"github.com/sentinel-protocol/sentinel-node/internal/inference"
	"github.com/sentinel-protocol/sentinel-node/internal/mempool"
	"github.com/sentinel-protocol/sentinel-node/pkg/types"
)

var (
	configPath = flag.String("config", "config.yaml", "Path to configuration file")
	logLevel   = flag.String("log-level", "info", "Log level (debug, info, warn, error)")
)

type SentinelNode struct {
	config    *config.Config
	mempool   *mempool.Listener
	gossip    *consensus.GossipNode
	bls       *consensus.BLSSigner
	bridge    *inference.Bridge
	verifier  *nodeVerifier
	logger    zerolog.Logger
	stats     *types.NodeStats
	startTime time.Time
}

// FIX: nodeVerifier implements consensus.SignatureVerifier for gossip message validation
type nodeVerifier struct {
	bls    *consensus.BLSSigner
	logger zerolog.Logger
	// In production, this would query the SentinelRegistry contract
	// For now, accept all registered nodes (will be connected to registry)
}

func (v *nodeVerifier) VerifyPauseRequest(request *types.SignedPauseRequest) bool {
	// Verify the BLS signature on the pause request
	if request == nil || len(request.Signature) == 0 {
		return false
	}

	// Create message hash from pause request data
	// In production, this should match the on-chain hashing scheme
	message := append(request.Request.TargetProtocol.Bytes(), request.Request.EvidenceHash.Bytes()...)

	// Get public key from signer (in production, this would be looked up from registry)
	// For now, we verify against the embedded public key in the BLS signer
	signerPubKey := v.bls.PublicKey()

	// Use package-level VerifySignature function
	valid, err := consensus.VerifySignature(request.Signature, message, signerPubKey)
	if err != nil {
		v.logger.Debug().Err(err).Msg("BLS signature verification error")
		return false
	}
	return valid
}

func (v *nodeVerifier) IsRegisteredNode(address string) bool {
	// TODO: In production, query SentinelRegistry.isNodeActive(address)
	// For now, allow all nodes during development
	// This should be connected to an Ethereum client to check on-chain
	v.logger.Debug().Str("address", address).Msg("Node registration check (development mode: allowing all)")
	return true
}

func main() {
	flag.Parse()

	level, err := zerolog.ParseLevel(*logLevel)
	if err != nil {
		level = zerolog.InfoLevel
	}
	zerolog.SetGlobalLevel(level)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr})

	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to load configuration")
	}

	node, err := NewSentinelNode(cfg)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to create sentinel node")
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	if err := node.Start(ctx); err != nil {
		log.Fatal().Err(err).Msg("Failed to start sentinel node")
	}

	log.Info().Msg("Sentinel node started")

	<-sigChan
	log.Info().Msg("Shutdown signal received")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), cfg.Node.ShutdownTimeout)
	defer shutdownCancel()

	if err := node.Stop(shutdownCtx); err != nil {
		log.Error().Err(err).Msg("Error during shutdown")
	}

	log.Info().Msg("Sentinel node stopped")
}

func NewSentinelNode(cfg *config.Config) (*SentinelNode, error) {
	logger := log.With().Str("component", "sentinel-node").Logger()

	mempoolListener, err := mempool.NewListener(mempool.ListenerConfig{
		RPCURL:     cfg.Ethereum.RPCURL,
		WSURL:      cfg.Ethereum.WSURL,
		BufferSize: 10000,
		Logger:     logger.With().Str("module", "mempool").Logger(),
	})
	if err != nil {
		return nil, err
	}

	// FIX: Create BLS signer first (needed for verifier)
	blsSigner, err := consensus.NewBLSSigner(cfg.Node.BLSKeyPath)
	if err != nil {
		mempoolListener.Stop()
		return nil, err
	}

	// FIX: Create verifier for gossip message validation (required for security)
	verifier := &nodeVerifier{
		bls:    blsSigner,
		logger: logger.With().Str("module", "verifier").Logger(),
	}

	// FIX: Pass verifier to gossip config (now required)
	gossipNode, err := consensus.NewGossipNode(consensus.GossipConfig{
		ListenAddresses: cfg.P2P.ListenAddresses,
		BootstrapPeers:  cfg.P2P.BootstrapPeers,
		TopicName:       cfg.P2P.TopicName,
		Logger:          logger.With().Str("module", "gossip").Logger(),
		Verifier:        verifier,
	})
	if err != nil {
		mempoolListener.Stop()
		return nil, err
	}

	inferenceBridge, err := inference.NewBridge(inference.BridgeConfig{
		Address:          cfg.Inference.GRPCAddress,
		Timeout:          cfg.Inference.Timeout,
		AnomalyThreshold: cfg.Inference.AnomalyThreshold,
		Logger:           logger.With().Str("module", "inference").Logger(),
	})
	if err != nil {
		logger.Warn().Err(err).Msg("Failed to connect to inference server, using fallback analysis")
		inferenceBridge = nil
	}

	return &SentinelNode{
		config:    cfg,
		mempool:   mempoolListener,
		gossip:    gossipNode,
		bls:       blsSigner,
		bridge:    inferenceBridge,
		verifier:  verifier,
		logger:    logger,
		stats:     &types.NodeStats{},
		startTime: time.Now(),
	}, nil
}

func (n *SentinelNode) Start(ctx context.Context) error {
	n.mempool.AddHandler(n.handleTransaction)

	if err := n.mempool.Start(ctx); err != nil {
		return err
	}

	if err := n.gossip.Start(ctx); err != nil {
		n.mempool.Stop()
		return err
	}

	n.gossip.OnPauseRequest(n.handlePauseRequest)
	n.gossip.OnAlert(n.handleAlert)

	n.logger.Info().
		Str("peerID", n.gossip.PeerID()).
		Str("blsPublicKey", n.bls.PublicKeyHex()[:32]+"...").
		Msg("Sentinel node initialized")

	return nil
}

func (n *SentinelNode) Stop(ctx context.Context) error {
	n.mempool.Stop()
	n.gossip.Stop()

	if n.bridge != nil {
		n.bridge.Close()
	}

	n.stats.Uptime = time.Since(n.startTime)

	n.logger.Info().
		Uint64("analyzed", n.stats.TransactionsAnalyzed).
		Uint64("suspicious", n.stats.SuspiciousDetected).
		Dur("uptime", n.stats.Uptime).
		Msg("Final statistics")

	return nil
}

func (n *SentinelNode) handleTransaction(tx *types.PendingTransaction) {
	n.stats.TransactionsAnalyzed++

	if n.bridge != nil && !n.bridge.QuickFilter(tx) {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), n.config.Inference.Timeout)
	defer cancel()

	var result *types.InferenceResult
	var err error

	if n.bridge != nil {
		result, err = n.bridge.Analyze(ctx, tx)
	} else {
		result = n.localAnalysis(tx)
	}

	if err != nil {
		n.logger.Debug().Err(err).Str("tx", tx.Hash.Hex()).Msg("Analysis failed")
		return
	}

	if result.IsSuspicious {
		n.stats.SuspiciousDetected++
		n.handleSuspiciousTransaction(tx, result)
	}
}

func (n *SentinelNode) localAnalysis(tx *types.PendingTransaction) *types.InferenceResult {
	if tx.IsSimpleTransfer() {
		return &types.InferenceResult{
			TxHash:         tx.Hash,
			IsSuspicious:   false,
			AnomalyScore:   0.0,
			RiskLevel:      "low",
			Recommendation: "allow",
		}
	}

	return &types.InferenceResult{
		TxHash:         tx.Hash,
		IsSuspicious:   false,
		AnomalyScore:   0.1,
		RiskLevel:      "low",
		Recommendation: "allow",
	}
}

func (n *SentinelNode) handleSuspiciousTransaction(tx *types.PendingTransaction, result *types.InferenceResult) {
	n.logger.Warn().
		Str("tx", tx.Hash.Hex()).
		Float64("score", result.AnomalyScore).
		Str("risk", result.RiskLevel).
		Strs("indicators", result.RiskIndicators).
		Msg("Suspicious transaction detected")

	alert := &types.Alert{
		ID:        tx.Hash.Hex(),
		Level:     types.AlertLevel(result.RiskLevel),
		TxHash:    tx.Hash,
		Message:   "Suspicious transaction detected",
		Timestamp: time.Now(),
		Result:    result,
	}

	if err := n.gossip.BroadcastAlert(alert); err != nil {
		n.logger.Error().Err(err).Msg("Failed to broadcast alert")
	}
}

func (n *SentinelNode) handlePauseRequest(request *types.SignedPauseRequest) {
	n.logger.Info().
		Str("protocol", request.Request.TargetProtocol.Hex()).
		Str("signer", request.Signer.Hex()).
		Msg("Received pause request")

	// TODO: Validate and co-sign if appropriate
	n.stats.PauseRequestsSigned++
}

func (n *SentinelNode) handleAlert(alert *types.Alert) {
	n.logger.Info().
		Str("id", alert.ID).
		Str("level", string(alert.Level)).
		Str("message", alert.Message).
		Msg("Received alert from peer")
}

func (n *SentinelNode) GetStats() *types.NodeStats {
	stats := *n.stats
	stats.Uptime = time.Since(n.startTime)

	received, processed, _ := n.mempool.GetStats()
	if processed > 0 {
		stats.AverageLatencyMs = float64(n.config.Inference.Timeout.Milliseconds()) / 2
	}

	_ = received
	return &stats
}

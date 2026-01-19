package consensus

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
	"github.com/rs/zerolog"

	"github.com/sentinel-protocol/sentinel-node/pkg/types"
)

type MessageType string

const (
	MessageTypePauseRequest    MessageType = "pause_request"
	MessageTypeSignature       MessageType = "signature"
	MessageTypeHeartbeat       MessageType = "heartbeat"
	MessageTypeAlert           MessageType = "alert"
)

type GossipMessage struct {
	Type      MessageType     `json:"type"`
	Sender    string          `json:"sender"`
	Timestamp time.Time       `json:"timestamp"`
	Payload   json.RawMessage `json:"payload"`
}

type PauseRequestHandler func(*types.SignedPauseRequest)
type SignatureHandler func(requestID string, signature []byte, signer string)
type AlertHandler func(*types.Alert)

// SignatureVerifier validates message signatures from peers
type SignatureVerifier interface {
	// VerifyPauseRequest verifies the BLS signature on a pause request
	VerifyPauseRequest(request *types.SignedPauseRequest) bool
	// IsRegisteredNode checks if an address is a registered active node
	IsRegisteredNode(address string) bool
}

type GossipNode struct {
	host      host.Host
	pubsub    *pubsub.PubSub
	topic     *pubsub.Topic
	sub       *pubsub.Subscription
	topicName string

	pauseHandlers     []PauseRequestHandler
	signatureHandlers []SignatureHandler
	alertHandlers     []AlertHandler

	peers    map[peer.ID]*PeerInfo
	peersMu  sync.RWMutex
	running  bool
	mu       sync.RWMutex
	wg       sync.WaitGroup

	// FIX: Add signature verifier for message authentication
	verifier SignatureVerifier

	logger zerolog.Logger
}

type PeerInfo struct {
	ID            peer.ID
	LastHeartbeat time.Time
	IsActive      bool
}

type GossipConfig struct {
	ListenAddresses []string
	BootstrapPeers  []string
	TopicName       string
	Logger          zerolog.Logger
	// Verifier validates message signatures (REQUIRED for security)
	Verifier        SignatureVerifier
}

func NewGossipNode(cfg GossipConfig) (*GossipNode, error) {
	// FIX: Require verifier for security - cannot operate without signature validation
	if cfg.Verifier == nil {
		return nil, fmt.Errorf("signature verifier is required for secure gossip operation")
	}

	h, err := libp2p.New(
		libp2p.ListenAddrStrings(cfg.ListenAddresses...),
	)
	if err != nil {
		return nil, err
	}

	ps, err := pubsub.NewGossipSub(context.Background(), h)
	if err != nil {
		h.Close()
		return nil, err
	}

	topic, err := ps.Join(cfg.TopicName)
	if err != nil {
		h.Close()
		return nil, err
	}

	sub, err := topic.Subscribe()
	if err != nil {
		topic.Close()
		h.Close()
		return nil, err
	}

	node := &GossipNode{
		host:      h,
		pubsub:    ps,
		topic:     topic,
		sub:       sub,
		topicName: cfg.TopicName,
		peers:     make(map[peer.ID]*PeerInfo),
		verifier:  cfg.Verifier,
		logger:    cfg.Logger,
	}

	for _, addr := range cfg.BootstrapPeers {
		peerInfo, err := peer.AddrInfoFromString(addr)
		if err != nil {
			cfg.Logger.Warn().Err(err).Str("addr", addr).Msg("Invalid bootstrap peer address")
			continue
		}

		if err := h.Connect(context.Background(), *peerInfo); err != nil {
			cfg.Logger.Warn().Err(err).Str("peer", peerInfo.ID.String()).Msg("Failed to connect to bootstrap peer")
		}
	}

	return node, nil
}

func (g *GossipNode) Start(ctx context.Context) error {
	g.mu.Lock()
	if g.running {
		g.mu.Unlock()
		return nil
	}
	g.running = true
	g.mu.Unlock()

	g.wg.Add(2)
	go g.listenLoop(ctx)
	go g.heartbeatLoop(ctx)

	g.logger.Info().
		Str("peerID", g.host.ID().String()).
		Strs("addrs", g.ListenAddresses()).
		Msg("Gossip node started")

	return nil
}

func (g *GossipNode) Stop() {
	g.mu.Lock()
	g.running = false
	g.mu.Unlock()

	g.wg.Wait()

	g.sub.Cancel()
	g.topic.Close()
	g.host.Close()

	g.logger.Info().Msg("Gossip node stopped")
}

func (g *GossipNode) OnPauseRequest(handler PauseRequestHandler) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.pauseHandlers = append(g.pauseHandlers, handler)
}

func (g *GossipNode) OnSignature(handler SignatureHandler) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.signatureHandlers = append(g.signatureHandlers, handler)
}

func (g *GossipNode) OnAlert(handler AlertHandler) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.alertHandlers = append(g.alertHandlers, handler)
}

func (g *GossipNode) BroadcastPauseRequest(request *types.SignedPauseRequest) error {
	payload, err := json.Marshal(request)
	if err != nil {
		return err
	}

	msg := GossipMessage{
		Type:      MessageTypePauseRequest,
		Sender:    g.host.ID().String(),
		Timestamp: time.Now(),
		Payload:   payload,
	}

	return g.broadcast(msg)
}

func (g *GossipNode) BroadcastSignature(requestID string, signature []byte) error {
	payload := struct {
		RequestID string `json:"requestId"`
		Signature []byte `json:"signature"`
	}{
		RequestID: requestID,
		Signature: signature,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	msg := GossipMessage{
		Type:      MessageTypeSignature,
		Sender:    g.host.ID().String(),
		Timestamp: time.Now(),
		Payload:   payloadBytes,
	}

	return g.broadcast(msg)
}

func (g *GossipNode) BroadcastAlert(alert *types.Alert) error {
	payload, err := json.Marshal(alert)
	if err != nil {
		return err
	}

	msg := GossipMessage{
		Type:      MessageTypeAlert,
		Sender:    g.host.ID().String(),
		Timestamp: time.Now(),
		Payload:   payload,
	}

	return g.broadcast(msg)
}

func (g *GossipNode) broadcast(msg GossipMessage) error {
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	return g.topic.Publish(context.Background(), data)
}

func (g *GossipNode) listenLoop(ctx context.Context) {
	defer g.wg.Done()

	for {
		msg, err := g.sub.Next(ctx)
		if err != nil {
			g.mu.RLock()
			running := g.running
			g.mu.RUnlock()
			if !running {
				return
			}
			g.logger.Error().Err(err).Msg("Error receiving message")
			continue
		}

		if msg.ReceivedFrom == g.host.ID() {
			continue
		}

		g.handleMessage(msg.Data, msg.ReceivedFrom)
	}
}

func (g *GossipNode) handleMessage(data []byte, from peer.ID) {
	var msg GossipMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		g.logger.Warn().Err(err).Msg("Failed to unmarshal gossip message")
		return
	}

	g.updatePeer(from)

	// FIX: Validate sender is a registered node (except for heartbeats)
	// Verifier is guaranteed non-nil since NewGossipNode requires it
	if msg.Type != MessageTypeHeartbeat {
		if !g.verifier.IsRegisteredNode(msg.Sender) {
			g.logger.Warn().
				Str("sender", msg.Sender).
				Str("type", string(msg.Type)).
				Msg("Rejected message from unregistered node")
			return
		}
	}

	g.mu.RLock()
	pauseHandlers := make([]PauseRequestHandler, len(g.pauseHandlers))
	copy(pauseHandlers, g.pauseHandlers)
	signatureHandlers := make([]SignatureHandler, len(g.signatureHandlers))
	copy(signatureHandlers, g.signatureHandlers)
	alertHandlers := make([]AlertHandler, len(g.alertHandlers))
	copy(alertHandlers, g.alertHandlers)
	g.mu.RUnlock()

	switch msg.Type {
	case MessageTypePauseRequest:
		var request types.SignedPauseRequest
		if err := json.Unmarshal(msg.Payload, &request); err != nil {
			g.logger.Warn().Err(err).Msg("Failed to unmarshal pause request")
			return
		}

		// FIX: Verify BLS signature on pause request (verifier guaranteed non-nil)
		if !g.verifier.VerifyPauseRequest(&request) {
			g.logger.Warn().
				Str("signer", request.Signer.Hex()).
				Msg("Rejected pause request with invalid signature")
			return
		}

		for _, handler := range pauseHandlers {
			handler(&request)
		}

	case MessageTypeSignature:
		var payload struct {
			RequestID string `json:"requestId"`
			Signature []byte `json:"signature"`
		}
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			g.logger.Warn().Err(err).Msg("Failed to unmarshal signature")
			return
		}
		for _, handler := range signatureHandlers {
			handler(payload.RequestID, payload.Signature, msg.Sender)
		}

	case MessageTypeAlert:
		var alert types.Alert
		if err := json.Unmarshal(msg.Payload, &alert); err != nil {
			g.logger.Warn().Err(err).Msg("Failed to unmarshal alert")
			return
		}
		for _, handler := range alertHandlers {
			handler(&alert)
		}

	case MessageTypeHeartbeat:
		// Already handled by updatePeer
	}
}

func (g *GossipNode) heartbeatLoop(ctx context.Context) {
	defer g.wg.Done()

	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			g.mu.RLock()
			running := g.running
			g.mu.RUnlock()
			if !running {
				return
			}

			msg := GossipMessage{
				Type:      MessageTypeHeartbeat,
				Sender:    g.host.ID().String(),
				Timestamp: time.Now(),
				Payload:   nil,
			}
			g.broadcast(msg)

			g.cleanupInactivePeers()
		}
	}
}

func (g *GossipNode) updatePeer(peerID peer.ID) {
	g.peersMu.Lock()
	defer g.peersMu.Unlock()

	if info, exists := g.peers[peerID]; exists {
		info.LastHeartbeat = time.Now()
		info.IsActive = true
	} else {
		g.peers[peerID] = &PeerInfo{
			ID:            peerID,
			LastHeartbeat: time.Now(),
			IsActive:      true,
		}
	}
}

func (g *GossipNode) cleanupInactivePeers() {
	g.peersMu.Lock()
	defer g.peersMu.Unlock()

	inactiveThreshold := time.Now().Add(-30 * time.Second)
	deleteThreshold := time.Now().Add(-5 * time.Minute) // FIX: Delete after 5 min of inactivity

	for id, info := range g.peers {
		if info.LastHeartbeat.Before(deleteThreshold) {
			// FIX: Actually delete stale peers to prevent memory leak
			delete(g.peers, id)
			g.logger.Debug().Str("peer", id.String()).Msg("Removed stale peer from tracking")
		} else if info.LastHeartbeat.Before(inactiveThreshold) {
			info.IsActive = false
		}
	}
}

func (g *GossipNode) PeerID() string {
	return g.host.ID().String()
}

func (g *GossipNode) ListenAddresses() []string {
	addrs := g.host.Addrs()
	result := make([]string, len(addrs))
	for i, addr := range addrs {
		result[i] = addr.String()
	}
	return result
}

func (g *GossipNode) ConnectedPeers() []string {
	peers := g.host.Network().Peers()
	result := make([]string, len(peers))
	for i, p := range peers {
		result[i] = p.String()
	}
	return result
}

func (g *GossipNode) ActivePeerCount() int {
	g.peersMu.RLock()
	defer g.peersMu.RUnlock()

	count := 0
	for _, info := range g.peers {
		if info.IsActive {
			count++
		}
	}
	return count
}

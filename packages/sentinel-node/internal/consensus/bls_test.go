package consensus

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGenerateKeyPair(t *testing.T) {
	keyPair, err := GenerateKeyPair()
	if err != nil {
		t.Fatalf("GenerateKeyPair failed: %v", err)
	}

	if keyPair.PrivateKey == nil {
		t.Error("PrivateKey is nil")
	}
	if keyPair.PublicKey == nil {
		t.Error("PublicKey is nil")
	}
}

func TestBLSSigner_Sign(t *testing.T) {
	signer, err := NewBLSSigner("")
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	message := []byte("test message")
	signature, err := signer.Sign(message)
	if err != nil {
		t.Fatalf("Sign failed: %v", err)
	}

	if len(signature) == 0 {
		t.Error("Signature is empty")
	}
}

func TestBLSSigner_PublicKey(t *testing.T) {
	signer, err := NewBLSSigner("")
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	pubKey := signer.PublicKey()
	if len(pubKey) == 0 {
		t.Error("PublicKey is empty")
	}
}

func TestBLSSigner_PublicKeyHex(t *testing.T) {
	signer, err := NewBLSSigner("")
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	pubKeyHex := signer.PublicKeyHex()
	if len(pubKeyHex) == 0 {
		t.Error("PublicKeyHex is empty")
	}
}

func TestVerifySignature(t *testing.T) {
	signer, err := NewBLSSigner("")
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	message := []byte("test message for verification")
	signature, err := signer.Sign(message)
	if err != nil {
		t.Fatalf("Sign failed: %v", err)
	}

	pubKey := signer.PublicKey()

	valid, err := VerifySignature(signature, message, pubKey)
	if err != nil {
		t.Fatalf("VerifySignature failed: %v", err)
	}

	if !valid {
		t.Error("Signature should be valid")
	}
}

func TestVerifySignature_InvalidSignature(t *testing.T) {
	signer, err := NewBLSSigner("")
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	message := []byte("test message")
	_, err = signer.Sign(message)
	if err != nil {
		t.Fatalf("Sign failed: %v", err)
	}

	pubKey := signer.PublicKey()

	// Verify with different message should fail
	differentMessage := []byte("different message")
	validSig, _ := signer.Sign(differentMessage)

	valid, err := VerifySignature(validSig, message, pubKey)
	if err != nil {
		t.Fatalf("VerifySignature failed: %v", err)
	}

	if valid {
		t.Error("Signature should be invalid for different message")
	}
}

func TestVerifySignature_InvalidPublicKey(t *testing.T) {
	signer1, _ := NewBLSSigner("")
	signer2, _ := NewBLSSigner("")

	message := []byte("test message")
	signature, _ := signer1.Sign(message)

	// Verify with different public key
	pubKey2 := signer2.PublicKey()

	valid, err := VerifySignature(signature, message, pubKey2)
	if err != nil {
		t.Fatalf("VerifySignature failed: %v", err)
	}

	if valid {
		t.Error("Signature should be invalid for different public key")
	}
}

func TestAggregateSignatures(t *testing.T) {
	signer1, _ := NewBLSSigner("")
	signer2, _ := NewBLSSigner("")

	message := []byte("shared message")

	sig1, _ := signer1.Sign(message)
	sig2, _ := signer2.Sign(message)

	aggSig, err := AggregateSignatures([][]byte{sig1, sig2})
	if err != nil {
		t.Fatalf("AggregateSignatures failed: %v", err)
	}

	if len(aggSig) == 0 {
		t.Error("Aggregated signature is empty")
	}
}

func TestAggregateSignatures_Empty(t *testing.T) {
	_, err := AggregateSignatures([][]byte{})
	if err != ErrAggregationFailed {
		t.Errorf("Expected ErrAggregationFailed, got %v", err)
	}
}

func TestAggregatePublicKeys(t *testing.T) {
	signer1, _ := NewBLSSigner("")
	signer2, _ := NewBLSSigner("")

	pubKey1 := signer1.PublicKey()
	pubKey2 := signer2.PublicKey()

	aggPubKey, err := AggregatePublicKeys([][]byte{pubKey1, pubKey2})
	if err != nil {
		t.Fatalf("AggregatePublicKeys failed: %v", err)
	}

	if len(aggPubKey) == 0 {
		t.Error("Aggregated public key is empty")
	}
}

func TestAggregatePublicKeys_Empty(t *testing.T) {
	_, err := AggregatePublicKeys([][]byte{})
	if err != ErrAggregationFailed {
		t.Errorf("Expected ErrAggregationFailed, got %v", err)
	}
}

func TestVerifyAggregatedSignature(t *testing.T) {
	signer1, _ := NewBLSSigner("")
	signer2, _ := NewBLSSigner("")

	message := []byte("shared message")

	sig1, _ := signer1.Sign(message)
	sig2, _ := signer2.Sign(message)

	aggSig, _ := AggregateSignatures([][]byte{sig1, sig2})

	pubKey1 := signer1.PublicKey()
	pubKey2 := signer2.PublicKey()

	messages := [][]byte{message, message}
	pubKeys := [][]byte{pubKey1, pubKey2}

	valid, err := VerifyAggregatedSignature(aggSig, messages, pubKeys)
	if err != nil {
		t.Fatalf("VerifyAggregatedSignature failed: %v", err)
	}

	if !valid {
		t.Error("Aggregated signature should be valid")
	}
}

func TestBLSSigner_SaveAndLoad(t *testing.T) {
	// Create temp directory
	tempDir := t.TempDir()
	keyPath := filepath.Join(tempDir, "test_key.bls")

	// Create new signer (will generate and save key)
	signer1, err := NewBLSSigner(keyPath)
	if err != nil {
		t.Fatalf("NewBLSSigner failed: %v", err)
	}

	pubKey1 := signer1.PublicKeyHex()

	// Verify file was created
	if _, err := os.Stat(keyPath); os.IsNotExist(err) {
		t.Error("Key file was not created")
	}

	// Load existing key
	signer2, err := NewBLSSigner(keyPath)
	if err != nil {
		t.Fatalf("NewBLSSigner (load) failed: %v", err)
	}

	pubKey2 := signer2.PublicKeyHex()

	// Public keys should match
	if pubKey1 != pubKey2 {
		t.Error("Loaded public key doesn't match original")
	}
}

func TestSerializeDeserializeKeyPair(t *testing.T) {
	keyPair, _ := GenerateKeyPair()

	serialized := serializeKeyPair(keyPair)
	if len(serialized) == 0 {
		t.Error("Serialized key pair is empty")
	}

	deserialized, err := deserializeKeyPair(serialized)
	if err != nil {
		t.Fatalf("deserializeKeyPair failed: %v", err)
	}

	// Verify the deserialized key pair matches
	if deserialized.PublicKey.Equal(keyPair.PublicKey) == false {
		t.Error("Deserialized public key doesn't match")
	}
}

package consensus

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"io"
	"math/big"
	"os"

	"github.com/consensys/gnark-crypto/ecc/bn254"
	"github.com/consensys/gnark-crypto/ecc/bn254/fr"
)

var (
	ErrInvalidSignature = errors.New("invalid BLS signature")
	ErrInvalidPublicKey = errors.New("invalid BLS public key")
	ErrAggregationFailed = errors.New("signature aggregation failed")
)

type BLSKeyPair struct {
	PrivateKey *fr.Element
	PublicKey  *bn254.G2Affine
}

type BLSSigner struct {
	keyPair *BLSKeyPair
}

func NewBLSSigner(keyPath string) (*BLSSigner, error) {
	keyPair, err := loadOrGenerateKey(keyPath)
	if err != nil {
		return nil, err
	}

	return &BLSSigner{keyPair: keyPair}, nil
}

func GenerateKeyPair() (*BLSKeyPair, error) {
	var privateKey fr.Element
	_, err := privateKey.SetRandom()
	if err != nil {
		return nil, err
	}

	_, _, _, g2Gen := bn254.Generators()

	var scalar big.Int
	privateKey.BigInt(&scalar)

	var publicKey bn254.G2Affine
	publicKey.ScalarMultiplication(&g2Gen, &scalar)

	return &BLSKeyPair{
		PrivateKey: &privateKey,
		PublicKey:  &publicKey,
	}, nil
}

func (s *BLSSigner) Sign(message []byte) ([]byte, error) {
	msgPoint := hashToG1(message)

	var scalar big.Int
	s.keyPair.PrivateKey.BigInt(&scalar)

	var signature bn254.G1Affine
	signature.ScalarMultiplication(&msgPoint, &scalar)

	return signature.Marshal(), nil
}

func (s *BLSSigner) PublicKey() []byte {
	return s.keyPair.PublicKey.Marshal()
}

func (s *BLSSigner) PublicKeyHex() string {
	return hex.EncodeToString(s.PublicKey())
}

func VerifySignature(signature, message, publicKey []byte) (bool, error) {
	var sig bn254.G1Affine
	if err := sig.Unmarshal(signature); err != nil {
		return false, ErrInvalidSignature
	}

	var pubKey bn254.G2Affine
	if err := pubKey.Unmarshal(publicKey); err != nil {
		return false, ErrInvalidPublicKey
	}

	msgPoint := hashToG1(message)

	_, _, _, g2Gen := bn254.Generators()

	var negMsgPoint bn254.G1Affine
	negMsgPoint.Neg(&msgPoint)

	valid, err := bn254.PairingCheck(
		[]bn254.G1Affine{sig, negMsgPoint},
		[]bn254.G2Affine{g2Gen, pubKey},
	)

	if err != nil {
		return false, err
	}

	return valid, nil
}

func AggregateSignatures(signatures [][]byte) ([]byte, error) {
	if len(signatures) == 0 {
		return nil, ErrAggregationFailed
	}

	var aggSig bn254.G1Affine
	if err := aggSig.Unmarshal(signatures[0]); err != nil {
		return nil, ErrInvalidSignature
	}

	for i := 1; i < len(signatures); i++ {
		var sig bn254.G1Affine
		if err := sig.Unmarshal(signatures[i]); err != nil {
			return nil, ErrInvalidSignature
		}

		var result bn254.G1Jac
		result.FromAffine(&aggSig)
		var sigJac bn254.G1Jac
		sigJac.FromAffine(&sig)
		result.AddAssign(&sigJac)
		aggSig.FromJacobian(&result)
	}

	return aggSig.Marshal(), nil
}

func AggregatePublicKeys(publicKeys [][]byte) ([]byte, error) {
	if len(publicKeys) == 0 {
		return nil, ErrAggregationFailed
	}

	var aggPubKey bn254.G2Affine
	if err := aggPubKey.Unmarshal(publicKeys[0]); err != nil {
		return nil, ErrInvalidPublicKey
	}

	for i := 1; i < len(publicKeys); i++ {
		var pubKey bn254.G2Affine
		if err := pubKey.Unmarshal(publicKeys[i]); err != nil {
			return nil, ErrInvalidPublicKey
		}

		var result bn254.G2Jac
		result.FromAffine(&aggPubKey)
		var pubKeyJac bn254.G2Jac
		pubKeyJac.FromAffine(&pubKey)
		result.AddAssign(&pubKeyJac)
		aggPubKey.FromJacobian(&result)
	}

	return aggPubKey.Marshal(), nil
}

func VerifyAggregatedSignature(aggSignature []byte, messages [][]byte, publicKeys [][]byte) (bool, error) {
	if len(messages) != len(publicKeys) || len(messages) == 0 {
		return false, ErrInvalidSignature
	}

	var aggSig bn254.G1Affine
	if err := aggSig.Unmarshal(aggSignature); err != nil {
		return false, ErrInvalidSignature
	}

	_, _, _, g2GenAff := bn254.Generators()

	g1Points := make([]bn254.G1Affine, len(messages)+1)
	g2Points := make([]bn254.G2Affine, len(messages)+1)

	g1Points[0] = aggSig
	g2Points[0] = g2GenAff

	for i := 0; i < len(messages); i++ {
		msgPoint := hashToG1(messages[i])
		var negMsgPoint bn254.G1Affine
		negMsgPoint.Neg(&msgPoint)
		g1Points[i+1] = negMsgPoint

		var pubKey bn254.G2Affine
		if err := pubKey.Unmarshal(publicKeys[i]); err != nil {
			return false, ErrInvalidPublicKey
		}
		g2Points[i+1] = pubKey
	}

	valid, err := bn254.PairingCheck(g1Points, g2Points)
	if err != nil {
		return false, err
	}

	return valid, nil
}

func hashToG1(message []byte) bn254.G1Affine {
	point, err := bn254.HashToG1(message, []byte("BLS_SIG_BN254G1_XMD:SHA-256_SVDW_RO_"))
	if err != nil {
		_, _, g1GenAff, _ := bn254.Generators()
		return g1GenAff
	}
	return point
}

func loadOrGenerateKey(keyPath string) (*BLSKeyPair, error) {
	if keyPath == "" {
		return GenerateKeyPair()
	}

	data, err := os.ReadFile(keyPath)
	if err != nil {
		if os.IsNotExist(err) {
			keyPair, err := GenerateKeyPair()
			if err != nil {
				return nil, err
			}

			if err := saveKey(keyPath, keyPair); err != nil {
				return nil, err
			}

			return keyPair, nil
		}
		return nil, err
	}

	return deserializeKeyPair(data)
}

func saveKey(keyPath string, keyPair *BLSKeyPair) error {
	data := serializeKeyPair(keyPair)
	return os.WriteFile(keyPath, data, 0600)
}

func serializeKeyPair(keyPair *BLSKeyPair) []byte {
	privBytes := keyPair.PrivateKey.Bytes()
	pubBytes := keyPair.PublicKey.Marshal()

	result := make([]byte, len(privBytes)+len(pubBytes))
	copy(result[:len(privBytes)], privBytes[:])
	copy(result[len(privBytes):], pubBytes)

	return result
}

func deserializeKeyPair(data []byte) (*BLSKeyPair, error) {
	if len(data) < 32 {
		return nil, errors.New("invalid key data")
	}

	var privateKey fr.Element
	privateKey.SetBytes(data[:32])

	var publicKey bn254.G2Affine
	if err := publicKey.Unmarshal(data[32:]); err != nil {
		return nil, err
	}

	return &BLSKeyPair{
		PrivateKey: &privateKey,
		PublicKey:  &publicKey,
	}, nil
}

func randomBytes(n int) ([]byte, error) {
	b := make([]byte, n)
	_, err := io.ReadFull(rand.Reader, b)
	return b, err
}

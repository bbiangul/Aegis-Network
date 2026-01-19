// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract BLSVerifier {
    uint256 constant N = 21888242871839275222246405745257275088696311157297823662689037894645226208583;
    uint256 constant P = 21888242871839275222246405745257275088548364400416034343698204186575808495617;

    uint256 constant G1_X = 1;
    uint256 constant G1_Y = 2;

    error InvalidSignature();
    error InvalidPublicKey();
    error AggregationFailed();
    error PointNotOnCurve();
    error InvalidSubgroup();

    struct G1Point {
        uint256 x;
        uint256 y;
    }

    struct G2Point {
        uint256[2] x;
        uint256[2] y;
    }

    function verifySignature(
        bytes memory signature,
        bytes memory message,
        bytes memory publicKey
    ) public view returns (bool) {
        // FIX: Use validated decoders to prevent malformed point attacks
        G1Point memory sig = decodeAndValidateG1Point(signature);
        G2Point memory pubKey = decodeAndValidateG2Point(publicKey);
        G1Point memory msgHash = hashToG1(message);

        return pairing(sig, getG2Generator(), negate(msgHash), pubKey);
    }

    function verifyAggregatedSignature(
        bytes memory aggregatedSignature,
        bytes[] memory messages,
        bytes[] memory publicKeys
    ) public view returns (bool) {
        if (messages.length != publicKeys.length) revert InvalidSignature();
        if (messages.length == 0) revert InvalidSignature();

        // FIX: Use validated decoder for aggregated signature
        G1Point memory aggSig = decodeAndValidateG1Point(aggregatedSignature);

        G1Point[] memory msgHashes = new G1Point[](messages.length);
        G2Point[] memory pubKeys = new G2Point[](messages.length);

        for (uint256 i = 0; i < messages.length; i++) {
            msgHashes[i] = hashToG1(messages[i]);
            // FIX: Use validated decoder for public keys
            pubKeys[i] = decodeAndValidateG2Point(publicKeys[i]);
        }

        return verifyMultiPairing(aggSig, msgHashes, pubKeys);
    }

    function aggregateSignatures(bytes[] memory signatures) public view returns (bytes memory) {
        if (signatures.length == 0) revert AggregationFailed();

        // FIX: Validate all signature points before aggregation
        G1Point memory result = decodeAndValidateG1Point(signatures[0]);

        for (uint256 i = 1; i < signatures.length; i++) {
            G1Point memory sig = decodeAndValidateG1Point(signatures[i]);
            result = addG1(result, sig);
        }

        return encodeG1Point(result);
    }

    function aggregatePublicKeys(bytes[] memory publicKeys) public view returns (bytes memory) {
        if (publicKeys.length == 0) revert AggregationFailed();

        // FIX: Validate all public key points before aggregation
        G2Point memory result = decodeAndValidateG2Point(publicKeys[0]);

        for (uint256 i = 1; i < publicKeys.length; i++) {
            G2Point memory pk = decodeAndValidateG2Point(publicKeys[i]);
            result = addG2(result, pk);
        }

        return encodeG2Point(result);
    }

    function hashToG1(bytes memory message) public view returns (G1Point memory) {
        uint256 h = uint256(keccak256(message)) % P;

        for (uint256 i = 0; i < 256; i++) {
            uint256 x = addmod(h, i, P);
            uint256 y2 = addmod(mulmod(mulmod(x, x, P), x, P), 3, P);
            uint256 y = modExp(y2, (P + 1) / 4, P);

            if (mulmod(y, y, P) == y2) {
                return G1Point(x, y);
            }
        }

        revert InvalidSignature();
    }

    function pairing(
        G1Point memory a1,
        G2Point memory a2,
        G1Point memory b1,
        G2Point memory b2
    ) internal view returns (bool) {
        uint256[12] memory input;

        input[0] = a1.x;
        input[1] = a1.y;
        input[2] = a2.x[1];
        input[3] = a2.x[0];
        input[4] = a2.y[1];
        input[5] = a2.y[0];

        input[6] = b1.x;
        input[7] = b1.y;
        input[8] = b2.x[1];
        input[9] = b2.x[0];
        input[10] = b2.y[1];
        input[11] = b2.y[0];

        uint256[1] memory result;
        bool success;

        assembly {
            success := staticcall(gas(), 8, input, 384, result, 32)
        }

        return success && result[0] == 1;
    }

    function verifyMultiPairing(
        G1Point memory aggSig,
        G1Point[] memory msgHashes,
        G2Point[] memory pubKeys
    ) internal view returns (bool) {
        uint256 n = msgHashes.length;
        uint256[] memory input = new uint256[](12 + n * 6);

        input[0] = aggSig.x;
        input[1] = aggSig.y;

        G2Point memory g2Gen = getG2Generator();
        input[2] = g2Gen.x[1];
        input[3] = g2Gen.x[0];
        input[4] = g2Gen.y[1];
        input[5] = g2Gen.y[0];

        for (uint256 i = 0; i < n; i++) {
            G1Point memory negHash = negate(msgHashes[i]);
            uint256 offset = 6 + i * 6;

            input[offset] = negHash.x;
            input[offset + 1] = negHash.y;
            input[offset + 2] = pubKeys[i].x[1];
            input[offset + 3] = pubKeys[i].x[0];
            input[offset + 4] = pubKeys[i].y[1];
            input[offset + 5] = pubKeys[i].y[0];
        }

        uint256[1] memory result;
        bool success;

        assembly {
            let len := mul(add(2, mul(n, 1)), 192)
            success := staticcall(gas(), 8, add(input, 32), len, result, 32)
        }

        return success && result[0] == 1;
    }

    function addG1(G1Point memory a, G1Point memory b) internal view returns (G1Point memory) {
        uint256[4] memory input;
        input[0] = a.x;
        input[1] = a.y;
        input[2] = b.x;
        input[3] = b.y;

        uint256[2] memory result;
        bool success;

        assembly {
            success := staticcall(gas(), 6, input, 128, result, 64)
        }

        require(success, "G1 addition failed");
        return G1Point(result[0], result[1]);
    }

    function addG2(G2Point memory a, G2Point memory b) internal pure returns (G2Point memory) {
        return G2Point(
            [addmod(a.x[0], b.x[0], P), addmod(a.x[1], b.x[1], P)],
            [addmod(a.y[0], b.y[0], P), addmod(a.y[1], b.y[1], P)]
        );
    }

    function negate(G1Point memory p) internal pure returns (G1Point memory) {
        if (p.x == 0 && p.y == 0) {
            return G1Point(0, 0);
        }
        return G1Point(p.x, P - (p.y % P));
    }

    function getG2Generator() internal pure returns (G2Point memory) {
        return G2Point(
            [
                11559732032986387107991004021392285783925812861821192530917403151452391805634,
                10857046999023057135944570762232829481370756359578518086990519993285655852781
            ],
            [
                4082367875863433681332203403145435568316851327593401208105741076214120093531,
                8495653923123431417604973247489272438418190587263600148770280649306958101930
            ]
        );
    }

    // FIX: Validate G1 point is on the curve (y² = x³ + 3 mod P)
    function isOnCurveG1(G1Point memory p) internal pure returns (bool) {
        if (p.x == 0 && p.y == 0) {
            return true; // Point at infinity is valid
        }
        if (p.x >= P || p.y >= P) {
            return false; // Coordinates must be in field
        }
        // y² mod P
        uint256 lhs = mulmod(p.y, p.y, P);
        // x³ + 3 mod P
        uint256 x2 = mulmod(p.x, p.x, P);
        uint256 x3 = mulmod(x2, p.x, P);
        uint256 rhs = addmod(x3, 3, P);
        return lhs == rhs;
    }

    // FIX: Validate G2 point is on the twisted curve
    // For BN254, G2 is defined over Fp2 with equation y² = x³ + 3/(9+u)
    // where u is the non-residue. We verify using the pairing precompile.
    function isValidG2Point(G2Point memory p) internal view returns (bool) {
        // Check coordinates are in field
        if (p.x[0] >= P || p.x[1] >= P || p.y[0] >= P || p.y[1] >= P) {
            return false;
        }
        // Point at infinity check
        if (p.x[0] == 0 && p.x[1] == 0 && p.y[0] == 0 && p.y[1] == 0) {
            return true;
        }
        // Use ecPairing precompile with identity to validate point format
        // If the point is invalid, the precompile will fail
        uint256[6] memory input;
        input[0] = G1_X;
        input[1] = G1_Y;
        input[2] = p.x[1];
        input[3] = p.x[0];
        input[4] = p.y[1];
        input[5] = p.y[0];

        uint256[1] memory result;
        bool success;
        assembly {
            success := staticcall(gas(), 8, input, 192, result, 32)
        }
        // If precompile succeeds, the G2 point is valid (even if pairing result is 0)
        return success;
    }

    // FIX: Subgroup check for G1 - verify point has correct order
    // For BN254, we check that N * P = O (point at infinity)
    function isInSubgroupG1(G1Point memory p) internal view returns (bool) {
        if (p.x == 0 && p.y == 0) {
            return true; // Point at infinity is in subgroup
        }
        // Multiply by curve order N using scalar multiplication precompile
        uint256[3] memory input;
        input[0] = p.x;
        input[1] = p.y;
        input[2] = N;

        uint256[2] memory result;
        bool success;
        assembly {
            success := staticcall(gas(), 7, input, 96, result, 64)
        }
        // Result should be point at infinity (0, 0)
        return success && result[0] == 0 && result[1] == 0;
    }

    function decodeG1Point(bytes memory data) internal pure returns (G1Point memory) {
        require(data.length >= 64, "Invalid G1 point");
        uint256 x;
        uint256 y;
        assembly {
            x := mload(add(data, 32))
            y := mload(add(data, 64))
        }
        return G1Point(x, y);
    }

    // FIX: Safe decoder with curve validation
    function decodeAndValidateG1Point(bytes memory data) internal view returns (G1Point memory) {
        G1Point memory p = decodeG1Point(data);
        if (!isOnCurveG1(p)) revert PointNotOnCurve();
        if (!isInSubgroupG1(p)) revert InvalidSubgroup();
        return p;
    }

    function decodeG2Point(bytes memory data) internal pure returns (G2Point memory) {
        require(data.length >= 128, "Invalid G2 point");
        uint256 x0;
        uint256 x1;
        uint256 y0;
        uint256 y1;
        assembly {
            x0 := mload(add(data, 32))
            x1 := mload(add(data, 64))
            y0 := mload(add(data, 96))
            y1 := mload(add(data, 128))
        }
        return G2Point([x0, x1], [y0, y1]);
    }

    // FIX: Safe decoder with curve validation for G2
    function decodeAndValidateG2Point(bytes memory data) internal view returns (G2Point memory) {
        G2Point memory p = decodeG2Point(data);
        if (!isValidG2Point(p)) revert PointNotOnCurve();
        return p;
    }

    function encodeG1Point(G1Point memory p) internal pure returns (bytes memory) {
        bytes memory result = new bytes(64);
        assembly {
            mstore(add(result, 32), mload(p))
            mstore(add(result, 64), mload(add(p, 32)))
        }
        return result;
    }

    function encodeG2Point(G2Point memory p) internal pure returns (bytes memory) {
        bytes memory result = new bytes(128);
        assembly {
            mstore(add(result, 32), mload(p))
            mstore(add(result, 64), mload(add(p, 32)))
            mstore(add(result, 96), mload(add(p, 64)))
            mstore(add(result, 128), mload(add(p, 96)))
        }
        return result;
    }

    function modExp(uint256 base, uint256 exponent, uint256 modulus) internal view returns (uint256 result) {
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, 32)
            mstore(add(ptr, 32), 32)
            mstore(add(ptr, 64), 32)
            mstore(add(ptr, 96), base)
            mstore(add(ptr, 128), exponent)
            mstore(add(ptr, 160), modulus)

            if iszero(staticcall(gas(), 5, ptr, 192, ptr, 32)) {
                revert(0, 0)
            }

            result := mload(ptr)
        }
    }
}

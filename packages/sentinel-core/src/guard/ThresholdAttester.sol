// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IAttester } from "./IAttester.sol";

/// @notice Immutable k-of-n ECDSA attester. Rotating the set means deploying a new attester and pointing the
///         guard at it, which is itself a delayed configuration change.
contract ThresholdAttester is IAttester {
    // secp256k1n / 2, rejects malleable signatures
    uint256 private constant HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    uint256 public immutable threshold;
    address[] public signers;
    mapping(address => bool) public isSigner;

    error InvalidSignerSet();

    constructor(address[] memory _signers, uint256 _threshold) {
        if (_threshold == 0 || _threshold > _signers.length) revert InvalidSignerSet();
        for (uint256 i = 0; i < _signers.length; i++) {
            address s = _signers[i];
            if (s == address(0) || isSigner[s]) revert InvalidSignerSet();
            isSigner[s] = true;
            signers.push(s);
        }
        threshold = _threshold;
    }

    /// @param proof Concatenated 65-byte (r, s, v) signatures over `digest`, ordered by ascending signer address.
    function isValidAttestation(bytes32 digest, bytes calldata proof) external view returns (bool) {
        if (proof.length % 65 != 0) return false;
        uint256 count = proof.length / 65;
        if (count < threshold) return false;

        address last;
        for (uint256 i = 0; i < count; i++) {
            bytes32 r;
            bytes32 s;
            uint8 v;
            assembly {
                let p := add(proof.offset, mul(i, 65))
                r := calldataload(p)
                s := calldataload(add(p, 32))
                v := byte(0, calldataload(add(p, 64)))
            }
            if (uint256(s) > HALF_N) return false;
            address signer = ecrecover(digest, v, r, s);
            // strictly ascending also rejects address(0) and duplicates
            if (signer <= last || !isSigner[signer]) return false;
            last = signer;
        }
        return true;
    }

    function signerCount() external view returns (uint256) {
        return signers.length;
    }
}

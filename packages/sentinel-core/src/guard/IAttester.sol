// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Anything that can vouch for a digest: a k-of-n key set today, a staked operator network later.
/// @dev The guard never asks an attester for permission to execute. An attestation can only shorten a
///      delay the owners already started, or temporarily tighten outflow limits.
interface IAttester {
    function isValidAttestation(bytes32 digest, bytes calldata proof) external view returns (bool);
}

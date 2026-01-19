// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "solmate/utils/ReentrancyGuard.sol";
import {Owned} from "solmate/auth/Owned.sol";
import {ISentinel} from "./interfaces/ISentinel.sol";
import {SentinelRegistry} from "./SentinelRegistry.sol";
import {SentinelShield} from "./SentinelShield.sol";
import {BLSVerifier} from "./BLSVerifier.sol";

contract SentinelRouter is ReentrancyGuard, Owned {
    SentinelRegistry public immutable registry;
    SentinelShield public immutable shield;
    BLSVerifier public immutable blsVerifier;

    uint256 public constant SIGNATURE_THRESHOLD_NUMERATOR = 20;
    uint256 public constant SIGNATURE_THRESHOLD_DENOMINATOR = 30;

    uint256 public constant MIN_SIGNERS = 5;
    uint256 public constant PAUSE_COOLDOWN = 1 hours;
    uint256 public constant MAX_REQUESTS_PER_NODE_PER_DAY = 5;  // FIX: Rate limiting

    struct PauseRequest {
        address targetProtocol;
        bytes32 evidenceHash;
        uint256 timestamp;
        address[] signers;
        bool executed;
    }

    mapping(bytes32 => PauseRequest) public pauseRequests;
    mapping(address => uint256) public lastPauseTime;
    mapping(bytes32 => mapping(address => bool)) public hasSigned;
    mapping(address => uint256) public nodeRequestCount;      // FIX: Rate limiting
    mapping(address => uint256) public nodeRequestResetTime;  // FIX: Rate limiting

    uint256 public totalPauses;
    uint256 public successfulPauses;

    error InsufficientSignatures();
    error InvalidSignature();
    error ProtocolNotRegistered();
    error AlreadyPaused();
    error CooldownActive();
    error AlreadySigned();
    error RequestAlreadyExecuted();
    error NodeNotRegistered();
    error ThresholdNotMet();
    error RateLimitExceeded();

    event PauseRequestCreated(bytes32 indexed requestId, address indexed protocol, bytes32 evidenceHash);
    event PauseRequestSigned(bytes32 indexed requestId, address indexed signer);
    event PauseExecuted(bytes32 indexed requestId, address indexed protocol, uint256 signerCount);
    event PauseFailed(bytes32 indexed requestId, address indexed protocol, string reason);

    constructor(
        address _registry,
        address _shield,
        address _blsVerifier,
        address _owner
    ) Owned(_owner) {
        registry = SentinelRegistry(_registry);
        shield = SentinelShield(_shield);
        blsVerifier = BLSVerifier(_blsVerifier);
    }

    function createPauseRequest(
        address targetProtocol,
        bytes32 evidenceHash
    ) external returns (bytes32 requestId) {
        if (!registry.isNodeActive(msg.sender)) revert NodeNotRegistered();
        if (!registry.isProtocolActive(targetProtocol)) revert ProtocolNotRegistered();

        // FIX: Rate limiting - reset counter if new day
        if (block.timestamp >= nodeRequestResetTime[msg.sender] + 1 days) {
            nodeRequestCount[msg.sender] = 0;
            nodeRequestResetTime[msg.sender] = block.timestamp;
        }
        if (nodeRequestCount[msg.sender] >= MAX_REQUESTS_PER_NODE_PER_DAY) {
            revert RateLimitExceeded();
        }
        nodeRequestCount[msg.sender]++;

        if (block.timestamp < lastPauseTime[targetProtocol] + PAUSE_COOLDOWN) {
            revert CooldownActive();
        }

        requestId = keccak256(abi.encodePacked(targetProtocol, evidenceHash, block.timestamp));

        address[] memory signers = new address[](1);
        signers[0] = msg.sender;

        pauseRequests[requestId] = PauseRequest({
            targetProtocol: targetProtocol,
            evidenceHash: evidenceHash,
            timestamp: block.timestamp,
            signers: signers,
            executed: false
        });

        hasSigned[requestId][msg.sender] = true;

        emit PauseRequestCreated(requestId, targetProtocol, evidenceHash);
        emit PauseRequestSigned(requestId, msg.sender);
    }

    function signPauseRequest(bytes32 requestId) external {
        if (!registry.isNodeActive(msg.sender)) revert NodeNotRegistered();

        PauseRequest storage request = pauseRequests[requestId];
        if (request.timestamp == 0) revert InvalidSignature();
        if (request.executed) revert RequestAlreadyExecuted();
        if (hasSigned[requestId][msg.sender]) revert AlreadySigned();

        hasSigned[requestId][msg.sender] = true;
        request.signers.push(msg.sender);

        emit PauseRequestSigned(requestId, msg.sender);

        _tryExecutePause(requestId);
    }

    function executePauseWithAggregatedSignature(
        address targetProtocol,
        bytes32 evidenceHash,
        bytes memory aggregatedSignature,
        address[] memory signers
    ) external nonReentrant {
        if (!registry.isProtocolActive(targetProtocol)) revert ProtocolNotRegistered();
        if (block.timestamp < lastPauseTime[targetProtocol] + PAUSE_COOLDOWN) {
            revert CooldownActive();
        }

        uint256 activeNodes = registry.getActiveNodeCount();
        // Use ceiling division for consistent threshold calculation
        uint256 requiredSigners = (activeNodes * SIGNATURE_THRESHOLD_NUMERATOR + SIGNATURE_THRESHOLD_DENOMINATOR - 1) / SIGNATURE_THRESHOLD_DENOMINATOR;
        if (requiredSigners < MIN_SIGNERS) requiredSigners = MIN_SIGNERS;

        if (signers.length < requiredSigners) revert InsufficientSignatures();

        bytes memory message = abi.encodePacked(targetProtocol, evidenceHash, block.chainid);

        bytes[] memory messages = new bytes[](signers.length);
        bytes[] memory publicKeys = new bytes[](signers.length);

        for (uint256 i = 0; i < signers.length; i++) {
            if (!registry.isNodeActive(signers[i])) revert NodeNotRegistered();

            messages[i] = message;

            (,,,,,, bytes32 blsKey) = registry.nodes(signers[i]);
            publicKeys[i] = abi.encodePacked(blsKey);
        }

        bool valid = blsVerifier.verifyAggregatedSignature(aggregatedSignature, messages, publicKeys);
        if (!valid) revert InvalidSignature();

        // Generate requestId for aggregated signature execution
        bytes32 requestId = keccak256(abi.encodePacked(targetProtocol, evidenceHash, block.timestamp, "aggregated"));
        _executePause(requestId, targetProtocol, evidenceHash, signers);
    }

    function _tryExecutePause(bytes32 requestId) internal {
        PauseRequest storage request = pauseRequests[requestId];

        // FIX: Check executed first to prevent race condition
        if (request.executed) return;

        uint256 activeNodes = registry.getActiveNodeCount();
        // FIX: Use ceiling division to prevent threshold manipulation
        uint256 requiredSigners = (activeNodes * SIGNATURE_THRESHOLD_NUMERATOR + SIGNATURE_THRESHOLD_DENOMINATOR - 1) / SIGNATURE_THRESHOLD_DENOMINATOR;
        if (requiredSigners < MIN_SIGNERS) requiredSigners = MIN_SIGNERS;

        if (request.signers.length >= requiredSigners) {
            // FIX: Mark executed BEFORE external calls to prevent reentrancy
            request.executed = true;
            _executePause(requestId, request.targetProtocol, request.evidenceHash, request.signers);
        }
    }

    function _executePause(
        bytes32 requestId,
        address targetProtocol,
        bytes32 evidenceHash,
        address[] memory signers
    ) internal {
        totalPauses++;
        lastPauseTime[targetProtocol] = block.timestamp;

        address pauseTarget = registry.getProtocolPauseTarget(targetProtocol);

        // FIX: Use gas-limited call to prevent DOS
        try ISentinel(pauseTarget).pause{gas: 100000}() {
            successfulPauses++;

            // FIX: Pass ALL signers for distributed bounty payout
            shield.emergencyPauseAndClaim(targetProtocol, evidenceHash, signers[0], signers);

            // FIX: Use consistent requestId instead of regenerating
            emit PauseExecuted(requestId, targetProtocol, signers.length);
        } catch Error(string memory reason) {
            emit PauseFailed(requestId, targetProtocol, reason);
        } catch {
            emit PauseFailed(requestId, targetProtocol, "Unknown error");
        }
    }

    function getPauseRequest(bytes32 requestId) external view returns (PauseRequest memory) {
        return pauseRequests[requestId];
    }

    function getSignerCount(bytes32 requestId) external view returns (uint256) {
        return pauseRequests[requestId].signers.length;
    }

    function getRequiredSignatures() external view returns (uint256) {
        uint256 activeNodes = registry.getActiveNodeCount();
        // Use ceiling division for consistent threshold calculation
        uint256 required = (activeNodes * SIGNATURE_THRESHOLD_NUMERATOR + SIGNATURE_THRESHOLD_DENOMINATOR - 1) / SIGNATURE_THRESHOLD_DENOMINATOR;
        return required < MIN_SIGNERS ? MIN_SIGNERS : required;
    }

    function canExecutePause(bytes32 requestId) external view returns (bool) {
        PauseRequest storage request = pauseRequests[requestId];
        if (request.executed) return false;

        uint256 activeNodes = registry.getActiveNodeCount();
        // Use ceiling division for consistent threshold calculation
        uint256 requiredSigners = (activeNodes * SIGNATURE_THRESHOLD_NUMERATOR + SIGNATURE_THRESHOLD_DENOMINATOR - 1) / SIGNATURE_THRESHOLD_DENOMINATOR;
        if (requiredSigners < MIN_SIGNERS) requiredSigners = MIN_SIGNERS;

        return request.signers.length >= requiredSigners;
    }

    function isOnCooldown(address protocol) external view returns (bool) {
        return block.timestamp < lastPauseTime[protocol] + PAUSE_COOLDOWN;
    }

    function getCooldownRemaining(address protocol) external view returns (uint256) {
        if (block.timestamp >= lastPauseTime[protocol] + PAUSE_COOLDOWN) {
            return 0;
        }
        return (lastPauseTime[protocol] + PAUSE_COOLDOWN) - block.timestamp;
    }

    function getStats() external view returns (uint256 total, uint256 successful) {
        return (totalPauses, successfulPauses);
    }
}

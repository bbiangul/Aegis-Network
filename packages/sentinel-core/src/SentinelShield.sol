// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "forge-std/interfaces/IERC20.sol";
import {ReentrancyGuard} from "solmate/utils/ReentrancyGuard.sol";
import {Owned} from "solmate/auth/Owned.sol";
import {ISentinelShield} from "./interfaces/ISentinelShield.sol";
import {SentinelRegistry} from "./SentinelRegistry.sol";

contract SentinelShield is ISentinelShield, ReentrancyGuard, Owned {
    IERC20 public immutable paymentToken;
    SentinelRegistry public immutable registry;

    uint256 public constant DISPUTE_WINDOW = 48 hours;
    uint256 public constant ORACLE_DECISION_WINDOW = 7 days;  // FIX: Oracle MUST decide within 7 days

    uint256 public constant BOUNTY_TIER_1 = 5_000 * 1e6;
    uint256 public constant BOUNTY_TIER_2 = 25_000 * 1e6;
    uint256 public constant BOUNTY_TIER_3 = 50_000 * 1e6;
    uint256 public constant BOUNTY_TIER_4 = 100_000 * 1e6;

    uint256 public constant TVL_TIER_1 = 1_000_000 * 1e6;
    uint256 public constant TVL_TIER_2 = 10_000_000 * 1e6;
    uint256 public constant TVL_TIER_3 = 100_000_000 * 1e6;

    mapping(address => uint256) public protocolBounties;
    mapping(uint256 => BountyClaim) public claims;

    uint256 public nextClaimId = 1;
    address public router;
    address public oracle;

    error InsufficientBounty();
    error InvalidClaim();
    error ClaimNotPending();
    error ClaimAlreadyDisputed();
    error DisputeWindowActive();
    error DisputeWindowExpired();
    error Unauthorized();
    error ProtocolNotRegistered();
    error NodeNotRegistered();
    error AlreadyClaimed();
    error OracleDecisionRequired();      // FIX: No auto-approval
    error OracleDecisionWindowExpired(); // FIX: Oracle must decide in time
    error EvidenceNotVerified();         // FIX: Evidence must be verified

    constructor(
        address _paymentToken,
        address _registry,
        address _owner
    ) Owned(_owner) {
        paymentToken = IERC20(_paymentToken);
        registry = SentinelRegistry(_registry);
    }

    function setRouter(address _router) external onlyOwner {
        router = _router;
    }

    function setOracle(address _oracle) external onlyOwner {
        oracle = _oracle;
    }

    function depositBounty(uint256 amount) external nonReentrant {
        if (!registry.isProtocolActive(msg.sender)) revert ProtocolNotRegistered();

        paymentToken.transferFrom(msg.sender, address(this), amount);
        protocolBounties[msg.sender] += amount;

        emit BountyDeposited(msg.sender, amount);
    }

    function withdrawBounty(uint256 amount) external nonReentrant {
        if (protocolBounties[msg.sender] < amount) revert InsufficientBounty();

        protocolBounties[msg.sender] -= amount;
        paymentToken.transfer(msg.sender, amount);

        emit BountyWithdrawn(msg.sender, amount);
    }

    modifier onlyRouter() {
        if (msg.sender != router) revert Unauthorized();
        _;
    }

    // FIX: Accept all signers for bounty distribution
    function emergencyPauseAndClaim(
        address targetProtocol,
        bytes32 evidenceHash,
        address claimingNode,
        address[] calldata allSigners
    ) external nonReentrant onlyRouter returns (uint256 claimId) {
        if (!registry.isNodeActive(claimingNode)) revert NodeNotRegistered();
        if (!registry.isProtocolActive(targetProtocol)) revert ProtocolNotRegistered();

        (uint256 protocolStake, uint256 tvl, , , bool isActive, ) = registry.protocols(targetProtocol);
        if (!isActive) revert ProtocolNotRegistered();

        uint256 bountyAmount = getBountyTier(tvl);
        if (protocolBounties[targetProtocol] < bountyAmount) {
            bountyAmount = protocolBounties[targetProtocol];
        }

        claimId = nextClaimId++;

        // FIX: Store all signers for distributed bounty payout
        address[] memory signersCopy = new address[](allSigners.length);
        for (uint256 i = 0; i < allSigners.length; i++) {
            signersCopy[i] = allSigners[i];
        }

        claims[claimId] = BountyClaim({
            id: claimId,
            node: claimingNode,
            targetProtocol: targetProtocol,
            tvlAtPause: tvl,
            bountyAmount: bountyAmount,
            claimTime: block.timestamp,
            disputeDeadline: block.timestamp + DISPUTE_WINDOW,
            oracleDeadline: block.timestamp + ORACLE_DECISION_WINDOW,  // FIX: Oracle deadline
            status: ClaimStatus.Pending,
            evidenceHash: evidenceHash,
            evidenceVerified: false,   // FIX: Must be verified by oracle
            allSigners: signersCopy    // FIX: All signers for distribution
        });

        emit ClaimCreated(claimId, claimingNode, targetProtocol, bountyAmount);
    }

    function disputeClaim(uint256 claimId) external nonReentrant {
        BountyClaim storage claim = claims[claimId];

        if (claim.status != ClaimStatus.Pending) revert ClaimNotPending();
        if (block.timestamp > claim.disputeDeadline) revert DisputeWindowExpired();
        if (msg.sender != claim.targetProtocol && msg.sender != owner) revert Unauthorized();

        claim.status = ClaimStatus.Disputed;

        emit ClaimDisputed(claimId, msg.sender);
    }

    function resolveDispute(uint256 claimId, bool approved) external {
        if (msg.sender != oracle && msg.sender != owner) revert Unauthorized();

        BountyClaim storage claim = claims[claimId];
        if (claim.status != ClaimStatus.Disputed) revert InvalidClaim();

        if (approved) {
            claim.status = ClaimStatus.Approved;
            claim.evidenceVerified = true;  // FIX: Implicitly verify evidence on approval
            emit ClaimApproved(claimId);
        } else {
            claim.status = ClaimStatus.Rejected;
            // FIX: Slash 50% instead of 10% for false positives
            registry.slashNode(claim.node, 5000, "False positive - dispute lost");
            emit ClaimRejected(claimId);
        }
    }

    // FIX: Oracle must verify evidence before payout
    function verifyEvidence(uint256 claimId) external {
        if (msg.sender != oracle && msg.sender != owner) revert Unauthorized();

        BountyClaim storage claim = claims[claimId];
        if (claim.status != ClaimStatus.Pending) revert ClaimNotPending();
        if (block.timestamp > claim.oracleDeadline) revert OracleDecisionWindowExpired();

        claim.evidenceVerified = true;
        claim.status = ClaimStatus.Approved;

        emit EvidenceVerified(claimId, claim.evidenceHash);
        emit ClaimApproved(claimId);
    }

    // FIX: Remove auto-approval, require oracle decision
    function processPayout(uint256 claimId) external nonReentrant {
        BountyClaim storage claim = claims[claimId];

        // FIX: No more auto-approval! Oracle MUST decide
        if (claim.status == ClaimStatus.Pending) {
            // If oracle deadline passed without decision, reject the claim
            if (block.timestamp > claim.oracleDeadline) {
                claim.status = ClaimStatus.Rejected;
                emit OracleDecisionExpired(claimId);
                emit ClaimRejected(claimId);
                return;
            }
            revert OracleDecisionRequired();
        }

        if (claim.status != ClaimStatus.Approved) revert InvalidClaim();
        if (!claim.evidenceVerified) revert EvidenceNotVerified();

        claim.status = ClaimStatus.Paid;

        uint256 payout = claim.bountyAmount;
        if (protocolBounties[claim.targetProtocol] < payout) {
            payout = protocolBounties[claim.targetProtocol];
        }

        protocolBounties[claim.targetProtocol] -= payout;

        // FIX: Distribute bounty to ALL signers, not just first
        uint256 signerCount = claim.allSigners.length;
        if (signerCount > 0) {
            uint256 perSignerPayout = payout / signerCount;
            uint256 remainder = payout % signerCount;

            for (uint256 i = 0; i < signerCount; i++) {
                uint256 amount = perSignerPayout;
                if (i == 0) amount += remainder;  // First signer gets remainder
                paymentToken.transfer(claim.allSigners[i], amount);
                emit BountyPaid(claimId, claim.allSigners[i], amount);
            }
        } else {
            // Fallback to original node if no signers array
            paymentToken.transfer(claim.node, payout);
            emit BountyPaid(claimId, claim.node, payout);
        }
    }

    function getClaim(uint256 claimId) external view returns (BountyClaim memory) {
        return claims[claimId];
    }

    function getProtocolBounty(address protocol) external view returns (uint256) {
        return protocolBounties[protocol];
    }

    function getBountyTier(uint256 tvl) public pure returns (uint256) {
        if (tvl >= TVL_TIER_3) return BOUNTY_TIER_4;
        if (tvl >= TVL_TIER_2) return BOUNTY_TIER_3;
        if (tvl >= TVL_TIER_1) return BOUNTY_TIER_2;
        return BOUNTY_TIER_1;
    }

    // FIX: Updated to require oracle approval and evidence verification
    function canProcessPayout(uint256 claimId) external view returns (bool) {
        BountyClaim storage claim = claims[claimId];

        // Only approved claims with verified evidence can be paid
        if (claim.status == ClaimStatus.Approved && claim.evidenceVerified) return true;

        return false;
    }

    function getClaimStatus(uint256 claimId) external view returns (ClaimStatus) {
        return claims[claimId].status;
    }

    function getTimeUntilPayout(uint256 claimId) external view returns (uint256) {
        BountyClaim storage claim = claims[claimId];

        if (claim.status != ClaimStatus.Pending) return 0;
        if (block.timestamp >= claim.disputeDeadline) return 0;

        return claim.disputeDeadline - block.timestamp;
    }
}

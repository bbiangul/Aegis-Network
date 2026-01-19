// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ISentinelShield {
    enum ClaimStatus {
        None,
        Pending,
        Disputed,
        Approved,
        Rejected,
        Paid
    }

    struct BountyClaim {
        uint256 id;
        address node;
        address targetProtocol;
        uint256 tvlAtPause;
        uint256 bountyAmount;
        uint256 claimTime;
        uint256 disputeDeadline;
        uint256 oracleDeadline;      // FIX: Oracle must decide by this time
        ClaimStatus status;
        bytes32 evidenceHash;
        bool evidenceVerified;        // FIX: Oracle must verify evidence
        address[] allSigners;         // FIX: All signers for bounty distribution
    }

    event BountyDeposited(address indexed protocol, uint256 amount);
    event BountyWithdrawn(address indexed protocol, uint256 amount);
    event ClaimCreated(uint256 indexed claimId, address indexed node, address indexed protocol, uint256 bountyAmount);
    event ClaimDisputed(uint256 indexed claimId, address indexed disputer);
    event ClaimApproved(uint256 indexed claimId);
    event ClaimRejected(uint256 indexed claimId);
    event BountyPaid(uint256 indexed claimId, address indexed node, uint256 amount);
    event EvidenceVerified(uint256 indexed claimId, bytes32 evidenceHash);  // FIX: Evidence verification event
    event OracleDecisionExpired(uint256 indexed claimId);                    // FIX: Oracle failed to decide

    function depositBounty(uint256 amount) external;
    function withdrawBounty(uint256 amount) external;
    function emergencyPauseAndClaim(address targetProtocol, bytes32 evidenceHash, address claimingNode, address[] calldata allSigners) external returns (uint256 claimId);
    function disputeClaim(uint256 claimId) external;
    function resolveDispute(uint256 claimId, bool approved) external;
    function verifyEvidence(uint256 claimId) external;           // FIX: Oracle must verify evidence
    function processPayout(uint256 claimId) external;
    function getClaim(uint256 claimId) external view returns (BountyClaim memory);
    function getProtocolBounty(address protocol) external view returns (uint256);
    function getBountyTier(uint256 tvl) external pure returns (uint256);
}

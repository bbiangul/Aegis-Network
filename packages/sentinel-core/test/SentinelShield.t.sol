// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SentinelToken.sol";
import "../src/SentinelRegistry.sol";
import "../src/SentinelShield.sol";
import "../src/interfaces/ISentinelShield.sol";

contract MockUSDC {
    string public name = "USD Coin";
    string public symbol = "USDC";
    uint8 public decimals = 6;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }
}

contract SentinelShieldTest is Test {
    SentinelToken public token;
    SentinelRegistry public registry;
    SentinelShield public shield;
    MockUSDC public usdc;

    address public owner = address(0x1);
    address public node1 = address(0x2);
    address public node2 = address(0x3);
    address public protocol1 = address(0x4);
    address public protocol2 = address(0x5);
    address public oracle = address(0x6);
    address public pauseTarget = address(0x7);
    address public router = address(0x8);

    bytes32 public blsKey1 = keccak256("bls_key_1");
    bytes32 public evidenceHash = keccak256("evidence");

    uint256 public constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 public constant DISPUTE_WINDOW = 48 hours;
    uint256 public constant ORACLE_DECISION_WINDOW = 7 days;

    // FIX: Helper to create signers array for emergencyPauseAndClaim
    function _createSignersArray(address signer) internal pure returns (address[] memory) {
        address[] memory signers = new address[](1);
        signers[0] = signer;
        return signers;
    }

    function _createSignersArray2(address signer1, address signer2) internal pure returns (address[] memory) {
        address[] memory signers = new address[](2);
        signers[0] = signer1;
        signers[1] = signer2;
        return signers;
    }

    function setUp() public {
        vm.startPrank(owner);

        // Deploy token and registry
        token = new SentinelToken(owner);
        registry = new SentinelRegistry(address(token), owner);
        token.setRegistry(address(registry));

        // Deploy USDC and shield
        usdc = new MockUSDC();
        shield = new SentinelShield(address(usdc), address(registry), owner);

        // Set shield in registry and configure
        registry.setShield(address(shield));
        registry.setRouter(router);
        shield.setRouter(router);
        shield.setOracle(oracle);

        // Transfer tokens to test accounts
        token.transfer(node1, 100_000 * 1e18);
        token.transfer(node2, 100_000 * 1e18);
        token.transfer(protocol1, 200_000 * 1e18);

        // Mint USDC for protocols
        usdc.mint(protocol1, 1_000_000 * 1e6); // 1M USDC
        usdc.mint(protocol2, 1_000_000 * 1e6);

        vm.stopPrank();

        // Register node1
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        // Register protocol1
        vm.startPrank(protocol1);
        token.approve(address(registry), 25_000 * 1e18);
        registry.registerProtocol(25_000 * 1e18, 5_000_000 * 1e18, pauseTarget);
        vm.stopPrank();
    }

    // ============ Bounty Deposit Tests ============

    function test_DepositBounty() public {
        uint256 depositAmount = 100_000 * 1e6;

        vm.startPrank(protocol1);
        usdc.approve(address(shield), depositAmount);
        shield.depositBounty(depositAmount);
        vm.stopPrank();

        assertEq(shield.getProtocolBounty(protocol1), depositAmount);
    }

    function test_DepositBounty_RevertsIfNotRegistered() public {
        vm.startPrank(protocol2); // Not registered
        usdc.approve(address(shield), 100_000 * 1e6);

        vm.expectRevert(SentinelShield.ProtocolNotRegistered.selector);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();
    }

    function test_WithdrawBounty() public {
        uint256 depositAmount = 100_000 * 1e6;

        vm.startPrank(protocol1);
        usdc.approve(address(shield), depositAmount);
        shield.depositBounty(depositAmount);

        uint256 withdrawAmount = 50_000 * 1e6;
        shield.withdrawBounty(withdrawAmount);
        vm.stopPrank();

        assertEq(shield.getProtocolBounty(protocol1), depositAmount - withdrawAmount);
    }

    function test_WithdrawBounty_RevertsIfInsufficient() public {
        vm.prank(protocol1);
        vm.expectRevert(SentinelShield.InsufficientBounty.selector);
        shield.withdrawBounty(100_000 * 1e6);
    }

    // ============ Emergency Pause and Claim Tests ============

    function test_EmergencyPauseAndClaim() public {
        // Deposit bounty first
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        // Router triggers emergency pause on behalf of node
        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        assertEq(claimId, 1);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(claim.node, node1);
        assertEq(claim.targetProtocol, protocol1);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Pending));
    }

    function test_EmergencyPauseAndClaim_RevertsIfNodeNotRegistered() public {
        vm.prank(router);
        vm.expectRevert(SentinelShield.NodeNotRegistered.selector);
        shield.emergencyPauseAndClaim(protocol1, evidenceHash, node2, _createSignersArray(node2)); // node2 not registered
    }

    function test_EmergencyPauseAndClaim_RevertsIfProtocolNotRegistered() public {
        vm.prank(router);
        vm.expectRevert(SentinelShield.ProtocolNotRegistered.selector);
        shield.emergencyPauseAndClaim(protocol2, evidenceHash, node1, _createSignersArray(node1)); // protocol2 not registered
    }

    // ============ Dispute Tests ============

    function test_DisputeClaim() public {
        // Setup: deposit bounty and create claim
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Protocol disputes
        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Disputed));
    }

    function test_DisputeClaim_RevertsIfNotPending() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Dispute once
        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        // Try to dispute again
        vm.prank(protocol1);
        vm.expectRevert(SentinelShield.ClaimNotPending.selector);
        shield.disputeClaim(claimId);
    }

    function test_DisputeClaim_RevertsIfExpired() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Fast forward past dispute window
        vm.warp(block.timestamp + DISPUTE_WINDOW + 1);

        vm.prank(protocol1);
        vm.expectRevert(SentinelShield.DisputeWindowExpired.selector);
        shield.disputeClaim(claimId);
    }

    function test_DisputeClaim_RevertsIfUnauthorized() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(node2); // Not the protocol or owner
        vm.expectRevert(SentinelShield.Unauthorized.selector);
        shield.disputeClaim(claimId);
    }

    // ============ Resolve Dispute Tests ============

    function test_ResolveDispute_Approved() public {
        // Setup claim and dispute
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        // Oracle approves (real attack)
        vm.prank(oracle);
        shield.resolveDispute(claimId, true);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Approved));
    }

    function test_ResolveDispute_Rejected_SlashesNode() public {
        // Setup claim and dispute
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        uint256 stakeBefore = registry.getNodeStake(node1);

        // Oracle rejects (false positive)
        vm.prank(oracle);
        shield.resolveDispute(claimId, false);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Rejected));

        // FIX: Node should be slashed 50% (5000 basis points) instead of 10%
        uint256 expectedSlash = (stakeBefore * 5000) / 10000;
        assertEq(registry.getNodeStake(node1), stakeBefore - expectedSlash);
    }

    function test_ResolveDispute_RevertsIfUnauthorized() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        vm.prank(node2); // Not oracle or owner
        vm.expectRevert(SentinelShield.Unauthorized.selector);
        shield.resolveDispute(claimId, true);
    }

    // ============ Process Payout Tests ============

    // FIX: Updated test - now requires oracle verification, no auto-approval
    function test_ProcessPayout_RequiresOracleVerification() public {
        uint256 depositAmount = 100_000 * 1e6;

        vm.startPrank(protocol1);
        usdc.approve(address(shield), depositAmount);
        shield.depositBounty(depositAmount);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Fast forward past dispute window (no dispute filed)
        vm.warp(block.timestamp + DISPUTE_WINDOW + 1);

        // FIX: Now requires oracle to verify evidence first
        vm.expectRevert(SentinelShield.OracleDecisionRequired.selector);
        shield.processPayout(claimId);

        // Oracle verifies evidence
        vm.prank(oracle);
        shield.verifyEvidence(claimId);

        uint256 balanceBefore = usdc.balanceOf(node1);
        shield.processPayout(claimId);

        // Node should receive bounty
        assertGt(usdc.balanceOf(node1), balanceBefore);
    }

    function test_ProcessPayout_AfterApproval() public {
        uint256 depositAmount = 100_000 * 1e6;

        vm.startPrank(protocol1);
        usdc.approve(address(shield), depositAmount);
        shield.depositBounty(depositAmount);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        vm.prank(oracle);
        shield.resolveDispute(claimId, true);

        uint256 balanceBefore = usdc.balanceOf(node1);

        shield.processPayout(claimId);

        assertGt(usdc.balanceOf(node1), balanceBefore);
    }

    // FIX: Updated test - now reverts with OracleDecisionRequired instead of DisputeWindowActive
    function test_ProcessPayout_RevertsIfOracleNotDecided() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Try to process before oracle decision
        vm.expectRevert(SentinelShield.OracleDecisionRequired.selector);
        shield.processPayout(claimId);
    }

    function test_ProcessPayout_RevertsIfRejected() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        vm.prank(oracle);
        shield.resolveDispute(claimId, false); // Rejected

        vm.expectRevert(SentinelShield.InvalidClaim.selector);
        shield.processPayout(claimId);
    }

    // ============ Bounty Tier Tests ============

    function test_GetBountyTier() public view {
        // < 1M TVL = BOUNTY_TIER_1 ($5k)
        assertEq(shield.getBountyTier(500_000 * 1e6), 5_000 * 1e6);

        // 1M-10M TVL = BOUNTY_TIER_2 ($25k)
        assertEq(shield.getBountyTier(5_000_000 * 1e6), 25_000 * 1e6);

        // 10M-100M TVL = BOUNTY_TIER_3 ($50k)
        assertEq(shield.getBountyTier(50_000_000 * 1e6), 50_000 * 1e6);

        // > 100M TVL = BOUNTY_TIER_4 ($100k)
        assertEq(shield.getBountyTier(200_000_000 * 1e6), 100_000 * 1e6);
    }

    // ============ View Functions Tests ============

    // FIX: Updated test - canProcessPayout now requires oracle verification
    function test_CanProcessPayout() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Should not be processable yet (pending, no oracle verification)
        assertFalse(shield.canProcessPayout(claimId));

        // Fast forward past dispute window - still not processable without oracle
        vm.warp(block.timestamp + DISPUTE_WINDOW + 1);
        assertFalse(shield.canProcessPayout(claimId));

        // Oracle verifies evidence
        vm.prank(oracle);
        shield.verifyEvidence(claimId);

        // Now should be processable
        assertTrue(shield.canProcessPayout(claimId));
    }

    function test_GetTimeUntilPayout() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        uint256 timeUntil = shield.getTimeUntilPayout(claimId);
        assertEq(timeUntil, DISPUTE_WINDOW);

        // Fast forward 12 hours
        vm.warp(block.timestamp + 12 hours);

        timeUntil = shield.getTimeUntilPayout(claimId);
        assertEq(timeUntil, DISPUTE_WINDOW - 12 hours);
    }

    // ============ Full Flow Integration Test ============

    // FIX: Updated test - now requires oracle verification
    function test_FullFlow_SuccessfulClaim() public {
        // 1. Protocol deposits bounty
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        // 2. Node detects attack and triggers pause
        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // 3. No dispute filed, oracle verifies evidence
        vm.prank(oracle);
        shield.verifyEvidence(claimId);

        // 4. Process payout
        uint256 nodeBefore = usdc.balanceOf(node1);
        shield.processPayout(claimId);

        // 5. Verify node received bounty
        assertGt(usdc.balanceOf(node1), nodeBefore);

        // 6. Verify claim status
        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Paid));
    }

    function test_FullFlow_DisputedAndApproved() public {
        // 1. Protocol deposits bounty
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        // 2. Node triggers pause
        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // 3. Protocol disputes
        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        // 4. Oracle approves (it was a real attack)
        vm.prank(oracle);
        shield.resolveDispute(claimId, true);

        // 5. Process payout
        uint256 nodeBefore = usdc.balanceOf(node1);
        shield.processPayout(claimId);

        // 6. Verify node received bounty
        assertGt(usdc.balanceOf(node1), nodeBefore);
    }

    function test_FullFlow_DisputedAndRejected() public {
        // 1. Protocol deposits bounty
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        // 2. Node triggers pause (false positive)
        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        uint256 stakeBefore = registry.getNodeStake(node1);

        // 3. Protocol disputes
        vm.prank(protocol1);
        shield.disputeClaim(claimId);

        // 4. Oracle rejects (false positive)
        vm.prank(oracle);
        shield.resolveDispute(claimId, false);

        // 5. FIX: Node should be slashed 50% (5000 basis points)
        uint256 expectedSlash = (stakeBefore * 5000) / 10000;
        assertEq(registry.getNodeStake(node1), stakeBefore - expectedSlash);

        // 6. Payout should fail
        vm.expectRevert(SentinelShield.InvalidClaim.selector);
        shield.processPayout(claimId);
    }

    // ============ New Tests for Oracle Verification ============

    function test_VerifyEvidence() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Oracle verifies evidence
        vm.prank(oracle);
        shield.verifyEvidence(claimId);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertTrue(claim.evidenceVerified);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Approved));
    }

    function test_VerifyEvidence_RevertsIfUnauthorized() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Non-oracle tries to verify
        vm.prank(node2);
        vm.expectRevert(SentinelShield.Unauthorized.selector);
        shield.verifyEvidence(claimId);
    }

    function test_OracleDeadlineExpired_RejectsClaim() public {
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(protocol1, evidenceHash, node1, _createSignersArray(node1));

        // Fast forward past oracle deadline
        vm.warp(block.timestamp + ORACLE_DECISION_WINDOW + 1);

        // Processing payout should reject the claim
        shield.processPayout(claimId);

        SentinelShield.BountyClaim memory claim = shield.getClaim(claimId);
        assertEq(uint256(claim.status), uint256(ISentinelShield.ClaimStatus.Rejected));
    }

    function test_BountyDistributedToAllSigners() public {
        // Register node2
        vm.startPrank(owner);
        token.transfer(node2, 100_000 * 1e18);
        vm.stopPrank();

        vm.startPrank(node2);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, keccak256("bls_key_2"));
        vm.stopPrank();

        // Deposit bounty
        vm.startPrank(protocol1);
        usdc.approve(address(shield), 100_000 * 1e6);
        shield.depositBounty(100_000 * 1e6);
        vm.stopPrank();

        // Create claim with multiple signers
        vm.prank(router);
        uint256 claimId = shield.emergencyPauseAndClaim(
            protocol1,
            evidenceHash,
            node1,
            _createSignersArray2(node1, node2)
        );

        // Oracle verifies
        vm.prank(oracle);
        shield.verifyEvidence(claimId);

        uint256 node1Before = usdc.balanceOf(node1);
        uint256 node2Before = usdc.balanceOf(node2);

        // Process payout
        shield.processPayout(claimId);

        // Both nodes should receive bounty
        assertGt(usdc.balanceOf(node1), node1Before);
        assertGt(usdc.balanceOf(node2), node2Before);
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SentinelToken.sol";
import "../src/SentinelRegistry.sol";

contract SentinelRegistryTest is Test {
    SentinelToken public token;
    SentinelRegistry public registry;

    address public owner = address(0x1);
    address public node1 = address(0x2);
    address public node2 = address(0x3);
    address public protocol1 = address(0x4);
    address public protocol2 = address(0x5);
    address public router = address(0x6);
    address public shield = address(0x7);

    bytes32 public blsKey1 = keccak256("bls_key_1");
    bytes32 public blsKey2 = keccak256("bls_key_2");

    uint256 public constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 public constant UNSTAKE_COOLDOWN = 21 days;

    function setUp() public {
        vm.startPrank(owner);
        token = new SentinelToken(owner);
        registry = new SentinelRegistry(address(token), owner);

        // Set registry in token for minting
        token.setRegistry(address(registry));

        // Set router and shield
        registry.setRouter(router);
        registry.setShield(shield);

        // Transfer tokens to test accounts
        token.transfer(node1, 100_000 * 1e18);
        token.transfer(node2, 100_000 * 1e18);
        token.transfer(protocol1, 200_000 * 1e18);
        token.transfer(protocol2, 200_000 * 1e18);
        vm.stopPrank();
    }

    // ============ Node Registration Tests ============

    function test_RegisterNode() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        assertTrue(registry.isNodeActive(node1));
        assertEq(registry.getNodeStake(node1), MIN_NODE_STAKE);
        assertEq(registry.getActiveNodeCount(), 1);
    }

    function test_RegisterNode_EmitsEvent() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);

        vm.expectEmit(true, false, false, true);
        emit SentinelRegistry.NodeRegistered(node1, MIN_NODE_STAKE, blsKey1);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();
    }

    function test_RegisterNode_RevertsIfInsufficientStake() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE - 1);

        vm.expectRevert(SentinelRegistry.InsufficientStake.selector);
        registry.registerNode(MIN_NODE_STAKE - 1, blsKey1);
        vm.stopPrank();
    }

    function test_RegisterNode_RevertsIfInvalidBLSKey() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);

        vm.expectRevert(SentinelRegistry.InvalidBLSKey.selector);
        registry.registerNode(MIN_NODE_STAKE, bytes32(0));
        vm.stopPrank();
    }

    function test_RegisterNode_RevertsIfAlreadyRegistered() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE * 2);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);

        vm.expectRevert(SentinelRegistry.AlreadyRegistered.selector);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();
    }

    // ============ Node Stake Increase Tests ============

    function test_IncreaseNodeStake() public {
        // Register first
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE * 2);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);

        uint256 increaseAmount = 5000 * 1e18;
        registry.increaseNodeStake(increaseAmount);
        vm.stopPrank();

        assertEq(registry.getNodeStake(node1), MIN_NODE_STAKE + increaseAmount);
    }

    function test_IncreaseNodeStake_RevertsIfNotActive() public {
        vm.startPrank(node1);
        token.approve(address(registry), 5000 * 1e18);

        vm.expectRevert(SentinelRegistry.NodeNotActive.selector);
        registry.increaseNodeStake(5000 * 1e18);
        vm.stopPrank();
    }

    function test_IncreaseNodeStake_RevertsIfZeroAmount() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);

        vm.expectRevert(SentinelRegistry.ZeroAmount.selector);
        registry.increaseNodeStake(0);
        vm.stopPrank();
    }

    // ============ Node Unstake Tests ============

    function test_RequestNodeUnstake() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE * 2);
        registry.registerNode(MIN_NODE_STAKE * 2, blsKey1);

        registry.requestNodeUnstake(MIN_NODE_STAKE);
        vm.stopPrank();

        (uint256 stake, uint256 unstakeTime, uint256 unstakeAmount, , , , ) = registry.nodes(node1);
        assertEq(unstakeAmount, MIN_NODE_STAKE);
        assertEq(unstakeTime, block.timestamp);
    }

    function test_RequestNodeUnstake_FullAmount() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);

        registry.requestNodeUnstake(MIN_NODE_STAKE);
        vm.stopPrank();
    }

    function test_RequestNodeUnstake_RevertsIfWouldGoBelowMinimum() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE + 1000 * 1e18);
        registry.registerNode(MIN_NODE_STAKE + 1000 * 1e18, blsKey1);

        // Try to unstake amount that would leave below minimum
        vm.expectRevert(SentinelRegistry.InsufficientStake.selector);
        registry.requestNodeUnstake(2000 * 1e18);
        vm.stopPrank();
    }

    function test_CompleteNodeUnstake() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        registry.requestNodeUnstake(MIN_NODE_STAKE);

        // Fast forward past cooldown
        vm.warp(block.timestamp + UNSTAKE_COOLDOWN + 1);

        uint256 balanceBefore = token.balanceOf(node1);
        registry.completeNodeUnstake();
        vm.stopPrank();

        assertEq(token.balanceOf(node1), balanceBefore + MIN_NODE_STAKE);
        assertFalse(registry.isNodeActive(node1));
    }

    function test_CompleteNodeUnstake_RevertsIfCooldownNotComplete() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        registry.requestNodeUnstake(MIN_NODE_STAKE);

        vm.expectRevert(SentinelRegistry.CooldownNotComplete.selector);
        registry.completeNodeUnstake();
        vm.stopPrank();
    }

    function test_CompleteNodeUnstake_RevertsIfNoPendingUnstake() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);

        vm.expectRevert(SentinelRegistry.NoPendingUnstake.selector);
        registry.completeNodeUnstake();
        vm.stopPrank();
    }

    // ============ Protocol Registration Tests ============

    function test_RegisterProtocol() public {
        uint256 tvl = 5_000_000 * 1e18; // 5M TVL
        uint256 requiredStake = registry.getRequiredProtocolStake(tvl);

        vm.startPrank(protocol1);
        token.approve(address(registry), requiredStake);
        registry.registerProtocol(requiredStake, tvl, address(0x100));
        vm.stopPrank();

        assertTrue(registry.isProtocolActive(protocol1));
        assertEq(registry.getProtocolStake(protocol1), requiredStake);
        assertEq(registry.getProtocolPauseTarget(protocol1), address(0x100));
    }

    function test_RegisterProtocol_RevertsIfInsufficientStake() public {
        uint256 tvl = 50_000_000 * 1e18; // 50M TVL requires STAKE_TIER_3
        uint256 requiredStake = registry.getRequiredProtocolStake(tvl);

        vm.startPrank(protocol1);
        token.approve(address(registry), requiredStake - 1);

        vm.expectRevert(SentinelRegistry.InsufficientStake.selector);
        registry.registerProtocol(requiredStake - 1, tvl, address(0x100));
        vm.stopPrank();
    }

    function test_GetRequiredProtocolStake_Tiers() public view {
        // < 1M TVL = STAKE_TIER_1 (5k)
        assertEq(registry.getRequiredProtocolStake(500_000 * 1e18), 5_000 * 1e18);

        // 1M-10M TVL = STAKE_TIER_2 (25k)
        assertEq(registry.getRequiredProtocolStake(5_000_000 * 1e18), 25_000 * 1e18);

        // 10M-100M TVL = STAKE_TIER_3 (50k)
        assertEq(registry.getRequiredProtocolStake(50_000_000 * 1e18), 50_000 * 1e18);

        // > 100M TVL = STAKE_TIER_4 (100k)
        assertEq(registry.getRequiredProtocolStake(200_000_000 * 1e18), 100_000 * 1e18);
    }

    // ============ Protocol TVL Update Tests ============

    function test_UpdateProtocolTVL() public {
        uint256 initialTVL = 500_000 * 1e18;
        uint256 newTVL = 800_000 * 1e18; // Still in same tier

        vm.startPrank(protocol1);
        token.approve(address(registry), 5_000 * 1e18);
        registry.registerProtocol(5_000 * 1e18, initialTVL, address(0x100));

        registry.updateProtocolTVL(newTVL);
        vm.stopPrank();

        (, uint256 tvl, , , , ) = registry.protocols(protocol1);
        assertEq(tvl, newTVL);
    }

    function test_UpdateProtocolTVL_RevertsIfInsufficientStake() public {
        uint256 initialTVL = 500_000 * 1e18;
        uint256 newTVL = 5_000_000 * 1e18; // Requires higher stake tier

        vm.startPrank(protocol1);
        token.approve(address(registry), 5_000 * 1e18);
        registry.registerProtocol(5_000 * 1e18, initialTVL, address(0x100));

        vm.expectRevert(SentinelRegistry.InsufficientStake.selector);
        registry.updateProtocolTVL(newTVL);
        vm.stopPrank();
    }

    // ============ Slashing Tests ============

    function test_SlashNode_ByRouter() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        uint256 stakeBefore = registry.getNodeStake(node1);

        vm.prank(router);
        registry.slashNode(node1, 1000, "False positive"); // 10% slash

        uint256 expectedSlash = (stakeBefore * 1000) / 10000;
        assertEq(registry.getNodeStake(node1), stakeBefore - expectedSlash);
    }

    function test_SlashNode_ByShield() public {
        // Stake 2x minimum so 5% slash doesn't deactivate
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE * 2);
        registry.registerNode(MIN_NODE_STAKE * 2, blsKey1);
        vm.stopPrank();

        vm.prank(shield);
        registry.slashNode(node1, 500, "Downtime"); // 5% slash

        // Node should still be active (above minimum after 5% slash of 2x stake)
        assertTrue(registry.isNodeActive(node1));
    }

    function test_SlashNode_DeactivatesIfBelowMinimum() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        vm.prank(router);
        registry.slashNode(node1, 5000, "Malicious behavior"); // 50% slash

        // Node should be deactivated (below minimum after 50% slash)
        assertFalse(registry.isNodeActive(node1));
    }

    function test_SlashNode_RevertsIfUnauthorized() public {
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        vm.prank(node2);
        vm.expectRevert(SentinelRegistry.Unauthorized.selector);
        registry.slashNode(node1, 1000, "Unauthorized slash");
    }

    // ============ Rewards Tests ============

    function test_ClaimRewards() public {
        // Register protocol to have TVL for rewards calculation
        vm.startPrank(protocol1);
        token.approve(address(registry), 25_000 * 1e18);
        registry.registerProtocol(25_000 * 1e18, 5_000_000 * 1e18, address(0x100));
        vm.stopPrank();

        // Register node
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        // Fast forward 1 day
        vm.warp(block.timestamp + 1 days);

        uint256 pendingRewards = registry.calculatePendingRewards(node1);
        assertGt(pendingRewards, 0);

        uint256 balanceBefore = token.balanceOf(node1);

        vm.prank(node1);
        registry.claimRewards();

        assertEq(token.balanceOf(node1), balanceBefore + pendingRewards);
    }

    function test_ClaimRewards_RevertsIfNotActive() public {
        vm.prank(node1);
        vm.expectRevert(SentinelRegistry.NodeNotActive.selector);
        registry.claimRewards();
    }

    // ============ View Functions Tests ============

    function test_GetActiveNodes() public {
        // Register two nodes
        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey1);
        vm.stopPrank();

        vm.startPrank(node2);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey2);
        vm.stopPrank();

        address[] memory activeNodes = registry.getActiveNodes();
        assertEq(activeNodes.length, 2);
    }

    function test_GetActiveProtocols() public {
        vm.startPrank(protocol1);
        token.approve(address(registry), 5_000 * 1e18);
        registry.registerProtocol(5_000 * 1e18, 500_000 * 1e18, address(0x100));
        vm.stopPrank();

        address[] memory activeProtocols = registry.getActiveProtocols();
        assertEq(activeProtocols.length, 1);
        assertEq(activeProtocols[0], protocol1);
    }

    // ============ Fuzz Tests ============

    function testFuzz_RegisterNode(uint256 stakeAmount) public {
        vm.assume(stakeAmount >= MIN_NODE_STAKE);
        vm.assume(stakeAmount <= token.balanceOf(node1));

        vm.startPrank(node1);
        token.approve(address(registry), stakeAmount);
        registry.registerNode(stakeAmount, blsKey1);
        vm.stopPrank();

        assertEq(registry.getNodeStake(node1), stakeAmount);
    }

    function testFuzz_SlashNode(uint256 basisPoints) public {
        vm.assume(basisPoints <= 10000);
        vm.assume(basisPoints > 0);

        vm.startPrank(node1);
        token.approve(address(registry), MIN_NODE_STAKE * 2);
        registry.registerNode(MIN_NODE_STAKE * 2, blsKey1);
        vm.stopPrank();

        uint256 stakeBefore = registry.getNodeStake(node1);

        vm.prank(router);
        registry.slashNode(node1, basisPoints, "Test slash");

        uint256 expectedSlash = (stakeBefore * basisPoints) / 10000;
        assertEq(registry.getNodeStake(node1), stakeBefore - expectedSlash);
    }
}

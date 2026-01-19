// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SentinelToken.sol";
import "../src/SentinelRegistry.sol";
import "../src/SentinelShield.sol";
import "../src/SentinelRouter.sol";
import "../src/BLSVerifier.sol";
import "../src/interfaces/ISentinel.sol";

contract MockPausable is ISentinel {
    bool public paused;
    bool public shouldFail;
    string public failReason;

    function pause() external override {
        if (shouldFail) {
            revert(failReason);
        }
        paused = true;
    }

    function unpause() external override {
        paused = false;
    }

    function setFail(bool _shouldFail, string memory _reason) external {
        shouldFail = _shouldFail;
        failReason = _reason;
    }
}

contract SentinelRouterTest is Test {
    SentinelToken public token;
    SentinelRegistry public registry;
    SentinelShield public shield;
    SentinelRouter public router;
    BLSVerifier public blsVerifier;
    MockPausable public mockProtocol;

    address public owner = address(0x1);
    address public protocol1 = address(0x10);

    // Node addresses
    address public node1 = address(0x101);
    address public node2 = address(0x102);
    address public node3 = address(0x103);
    address public node4 = address(0x104);
    address public node5 = address(0x105);
    address public node6 = address(0x106);
    address public node7 = address(0x107);

    // BLS keys (mock)
    bytes32 public blsKey1 = keccak256("bls_key_1");
    bytes32 public blsKey2 = keccak256("bls_key_2");
    bytes32 public blsKey3 = keccak256("bls_key_3");
    bytes32 public blsKey4 = keccak256("bls_key_4");
    bytes32 public blsKey5 = keccak256("bls_key_5");
    bytes32 public blsKey6 = keccak256("bls_key_6");
    bytes32 public blsKey7 = keccak256("bls_key_7");

    uint256 public constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 public constant PROTOCOL_STAKE = 25_000 * 1e18;
    uint256 public constant PROTOCOL_TVL = 5_000_000 * 1e18;

    bytes32 public evidenceHash = keccak256("exploit_evidence");

    function setUp() public {
        // Warp to a realistic timestamp (past cooldown period)
        vm.warp(1700000000);

        vm.startPrank(owner);

        // Deploy token
        token = new SentinelToken(owner);

        // Deploy registry
        registry = new SentinelRegistry(address(token), owner);
        token.setRegistry(address(registry));

        // Deploy BLS verifier
        blsVerifier = new BLSVerifier();

        // Deploy shield (will be set in router)
        shield = new SentinelShield(address(token), address(registry), owner);

        // Deploy router
        router = new SentinelRouter(
            address(registry),
            address(shield),
            address(blsVerifier),
            owner
        );

        // Set router in registry and shield
        registry.setRouter(address(router));
        registry.setShield(address(shield));
        shield.setRouter(address(router));

        // Deploy mock pausable protocol
        mockProtocol = new MockPausable();

        // Transfer tokens to test accounts
        token.transfer(node1, 200_000 * 1e18);
        token.transfer(node2, 200_000 * 1e18);
        token.transfer(node3, 200_000 * 1e18);
        token.transfer(node4, 200_000 * 1e18);
        token.transfer(node5, 200_000 * 1e18);
        token.transfer(node6, 200_000 * 1e18);
        token.transfer(node7, 200_000 * 1e18);
        token.transfer(protocol1, 500_000 * 1e18);

        vm.stopPrank();

        // Register protocol
        _registerProtocol();
    }

    function _registerProtocol() internal {
        vm.startPrank(protocol1);
        token.approve(address(registry), PROTOCOL_STAKE);
        registry.registerProtocol(PROTOCOL_STAKE, PROTOCOL_TVL, address(mockProtocol));

        // Deposit bounty into shield
        token.approve(address(shield), 50_000 * 1e18);
        shield.depositBounty(50_000 * 1e18);
        vm.stopPrank();
    }

    function _registerNode(address node, bytes32 blsKey) internal {
        vm.startPrank(node);
        token.approve(address(registry), MIN_NODE_STAKE);
        registry.registerNode(MIN_NODE_STAKE, blsKey);
        vm.stopPrank();
    }

    function _registerMinimumNodes() internal {
        _registerNode(node1, blsKey1);
        _registerNode(node2, blsKey2);
        _registerNode(node3, blsKey3);
        _registerNode(node4, blsKey4);
        _registerNode(node5, blsKey5);
    }

    // ============ Create Pause Request Tests ============

    function test_CreatePauseRequest() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        assertTrue(requestId != bytes32(0));
        assertEq(router.getSignerCount(requestId), 1);
    }

    function test_CreatePauseRequest_EmitsEvent() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        vm.expectEmit(true, true, false, true);
        emit SentinelRouter.PauseRequestCreated(
            keccak256(abi.encodePacked(protocol1, evidenceHash, block.timestamp)),
            protocol1,
            evidenceHash
        );
        router.createPauseRequest(protocol1, evidenceHash);
    }

    function test_CreatePauseRequest_RevertsIfNodeNotRegistered() public {
        vm.prank(node1);
        vm.expectRevert(SentinelRouter.NodeNotRegistered.selector);
        router.createPauseRequest(protocol1, evidenceHash);
    }

    function test_CreatePauseRequest_RevertsIfProtocolNotRegistered() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        vm.expectRevert(SentinelRouter.ProtocolNotRegistered.selector);
        router.createPauseRequest(address(0x999), evidenceHash);
    }

    function test_CreatePauseRequest_RevertsIfOnCooldown() public {
        _registerMinimumNodes();

        // Create and execute a pause
        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        // Sign with remaining nodes
        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);
        vm.prank(node5);
        router.signPauseRequest(requestId);

        // Try to create another request immediately
        vm.prank(node1);
        vm.expectRevert(SentinelRouter.CooldownActive.selector);
        router.createPauseRequest(protocol1, keccak256("new_evidence"));
    }

    // ============ Sign Pause Request Tests ============

    function test_SignPauseRequest() public {
        _registerNode(node1, blsKey1);
        _registerNode(node2, blsKey2);

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node2);
        vm.expectEmit(true, true, false, false);
        emit SentinelRouter.PauseRequestSigned(requestId, node2);
        router.signPauseRequest(requestId);

        assertEq(router.getSignerCount(requestId), 2);
    }

    function test_SignPauseRequest_RevertsIfNodeNotRegistered() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node2);
        vm.expectRevert(SentinelRouter.NodeNotRegistered.selector);
        router.signPauseRequest(requestId);
    }

    function test_SignPauseRequest_RevertsIfAlreadySigned() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node1);
        vm.expectRevert(SentinelRouter.AlreadySigned.selector);
        router.signPauseRequest(requestId);
    }

    function test_SignPauseRequest_RevertsIfInvalidRequest() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        vm.expectRevert(SentinelRouter.InvalidSignature.selector);
        router.signPauseRequest(keccak256("invalid_request_id"));
    }

    function test_SignPauseRequest_RevertsIfAlreadyExecuted() public {
        _registerMinimumNodes();

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        // Sign with enough nodes to execute
        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);
        vm.prank(node5);
        router.signPauseRequest(requestId);

        // Request should be executed now
        _registerNode(node6, blsKey6);
        vm.prank(node6);
        vm.expectRevert(SentinelRouter.RequestAlreadyExecuted.selector);
        router.signPauseRequest(requestId);
    }

    // ============ Pause Execution Tests ============

    function test_PauseExecutionOnThreshold() public {
        _registerMinimumNodes();

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        // Sign with remaining nodes to reach threshold
        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);
        vm.prank(node5);
        router.signPauseRequest(requestId);

        // Protocol should be paused
        assertTrue(mockProtocol.paused());

        // Stats should be updated
        (uint256 total, uint256 successful) = router.getStats();
        assertEq(total, 1);
        assertEq(successful, 1);
    }

    function test_PauseExecutionEmitsEvent() public {
        _registerMinimumNodes();

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);

        // Last signature triggers execution
        vm.prank(node5);
        vm.expectEmit(false, true, false, false);
        emit SentinelRouter.PauseExecuted(bytes32(0), protocol1, 5);
        router.signPauseRequest(requestId);
    }

    function test_PauseExecutionHandlesFailure() public {
        _registerMinimumNodes();

        // Make protocol fail on pause
        mockProtocol.setFail(true, "Protocol locked");

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);
        vm.prank(node5);
        router.signPauseRequest(requestId);

        // Protocol should not be paused
        assertFalse(mockProtocol.paused());

        // Stats should reflect failure
        (uint256 total, uint256 successful) = router.getStats();
        assertEq(total, 1);
        assertEq(successful, 0);
    }

    // ============ View Functions Tests ============

    function test_GetRequiredSignatures_MinimumNodes() public {
        // With less than 8 nodes, should require MIN_SIGNERS (5)
        _registerMinimumNodes();
        assertEq(router.getRequiredSignatures(), 5);
    }

    function test_GetRequiredSignatures_MoreNodes() public {
        // Register 15 nodes (20/30 * 15 = 10 required)
        _registerNode(node1, blsKey1);
        _registerNode(node2, blsKey2);
        _registerNode(node3, blsKey3);
        _registerNode(node4, blsKey4);
        _registerNode(node5, blsKey5);
        _registerNode(node6, blsKey6);
        _registerNode(node7, blsKey7);

        // Additional mock nodes
        for (uint256 i = 8; i <= 15; i++) {
            address nodeAddr = address(uint160(0x200 + i));
            vm.prank(owner);
            token.transfer(nodeAddr, MIN_NODE_STAKE);

            vm.startPrank(nodeAddr);
            token.approve(address(registry), MIN_NODE_STAKE);
            registry.registerNode(MIN_NODE_STAKE, keccak256(abi.encodePacked("bls_key_", i)));
            vm.stopPrank();
        }

        // 15 nodes * 20/30 = 10 required
        assertEq(router.getRequiredSignatures(), 10);
    }

    function test_CanExecutePause() public {
        _registerMinimumNodes();

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        assertFalse(router.canExecutePause(requestId));

        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);

        // Still need 1 more
        assertFalse(router.canExecutePause(requestId));

        vm.prank(node5);
        router.signPauseRequest(requestId);

        // Already executed, so canExecute returns false
        assertFalse(router.canExecutePause(requestId));
    }

    function test_IsOnCooldown() public {
        _registerMinimumNodes();

        assertFalse(router.isOnCooldown(protocol1));

        // Trigger pause
        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        vm.prank(node2);
        router.signPauseRequest(requestId);
        vm.prank(node3);
        router.signPauseRequest(requestId);
        vm.prank(node4);
        router.signPauseRequest(requestId);
        vm.prank(node5);
        router.signPauseRequest(requestId);

        assertTrue(router.isOnCooldown(protocol1));
        assertGt(router.getCooldownRemaining(protocol1), 0);

        // Fast forward past cooldown
        vm.warp(block.timestamp + 1 hours + 1);

        assertFalse(router.isOnCooldown(protocol1));
        assertEq(router.getCooldownRemaining(protocol1), 0);
    }

    function test_GetPauseRequest() public {
        _registerNode(node1, blsKey1);

        vm.prank(node1);
        bytes32 requestId = router.createPauseRequest(protocol1, evidenceHash);

        SentinelRouter.PauseRequest memory request = router.getPauseRequest(requestId);

        assertEq(request.targetProtocol, protocol1);
        assertEq(request.evidenceHash, evidenceHash);
        assertEq(request.signers.length, 1);
        assertEq(request.signers[0], node1);
        assertFalse(request.executed);
    }

    // ============ Fuzz Tests ============

    function testFuzz_RequiredSignatures(uint8 nodeCount) public {
        vm.assume(nodeCount > 0 && nodeCount <= 100);

        // Register nodes
        for (uint256 i = 0; i < nodeCount; i++) {
            address nodeAddr = address(uint160(0x1000 + i));
            vm.prank(owner);
            token.transfer(nodeAddr, MIN_NODE_STAKE);

            vm.startPrank(nodeAddr);
            token.approve(address(registry), MIN_NODE_STAKE);
            registry.registerNode(MIN_NODE_STAKE, keccak256(abi.encodePacked("fuzz_bls_", i)));
            vm.stopPrank();
        }

        uint256 required = router.getRequiredSignatures();
        // Use ceiling division to match contract
        uint256 expected = (uint256(nodeCount) * 20 + 29) / 30;
        if (expected < 5) expected = 5;

        assertEq(required, expected);
    }
}

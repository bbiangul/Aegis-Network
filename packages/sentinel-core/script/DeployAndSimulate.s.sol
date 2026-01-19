// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "forge-std/console.sol";
import "../src/SentinelToken.sol";
import "../src/SentinelRegistry.sol";
import "../src/SentinelShield.sol";
import "../src/SentinelRouter.sol";
import "../src/BLSVerifier.sol";
import "../src/interfaces/ISentinel.sol";

// Mock pausable protocol for testing
contract MockProtocol is ISentinel {
    bool public paused;
    uint256 public tvl = 5_000_000 * 1e18; // 5M TVL

    event Paused(address caller);
    event Unpaused(address caller);

    function pause() external override {
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external override {
        paused = false;
        emit Unpaused(msg.sender);
    }
}

contract DeployAndSimulate is Script {
    // Contracts
    SentinelToken public token;
    SentinelRegistry public registry;
    SentinelShield public shield;
    SentinelRouter public router;
    BLSVerifier public blsVerifier;
    MockProtocol public mockProtocol;

    // Test accounts (Anvil default accounts)
    address public deployer;
    address public node1;
    address public node2;
    address public node3;
    address public node4;
    address public node5;
    address public protocolOwner;
    address public oracle;

    // Constants
    uint256 constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 constant PROTOCOL_STAKE = 25_000 * 1e18;

    function run() external {
        // Get accounts from Anvil
        deployer = vm.addr(0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80);
        node1 = vm.addr(0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d);
        node2 = vm.addr(0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a);
        node3 = vm.addr(0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6);
        node4 = vm.addr(0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a);
        node5 = vm.addr(0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba);
        protocolOwner = vm.addr(0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e);
        oracle = vm.addr(0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356);

        console.log("=== SENTINEL PROTOCOL TESTNET SIMULATION ===");
        console.log("");

        // Step 1: Deploy contracts
        vm.startBroadcast(0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80);

        console.log("Step 1: Deploying contracts...");

        token = new SentinelToken(deployer);
        console.log("  SentinelToken deployed at:", address(token));

        registry = new SentinelRegistry(address(token), deployer);
        console.log("  SentinelRegistry deployed at:", address(registry));

        blsVerifier = new BLSVerifier();
        console.log("  BLSVerifier deployed at:", address(blsVerifier));

        shield = new SentinelShield(address(token), address(registry), deployer);
        console.log("  SentinelShield deployed at:", address(shield));

        router = new SentinelRouter(address(registry), address(shield), address(blsVerifier), deployer);
        console.log("  SentinelRouter deployed at:", address(router));

        mockProtocol = new MockProtocol();
        console.log("  MockProtocol deployed at:", address(mockProtocol));

        // Step 2: Configure contract relationships
        console.log("");
        console.log("Step 2: Configuring contract relationships...");

        token.setRegistry(address(registry));
        console.log("  Token registry set");

        registry.setRouter(address(router));
        console.log("  Registry router set");

        registry.setShield(address(shield));
        console.log("  Registry shield set");

        shield.setRouter(address(router));
        console.log("  Shield router set");

        shield.setOracle(oracle);
        console.log("  Shield oracle set");

        // Step 3: Distribute tokens
        console.log("");
        console.log("Step 3: Distributing tokens...");

        token.transfer(node1, 100_000 * 1e18);
        token.transfer(node2, 100_000 * 1e18);
        token.transfer(node3, 100_000 * 1e18);
        token.transfer(node4, 100_000 * 1e18);
        token.transfer(node5, 100_000 * 1e18);
        token.transfer(protocolOwner, 200_000 * 1e18);

        console.log("  Distributed 100k tokens to each of 5 nodes");
        console.log("  Distributed 200k tokens to protocol owner");

        vm.stopBroadcast();

        // Step 4: Register nodes
        console.log("");
        console.log("Step 4: Registering nodes...");

        _registerNode(0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d, node1, "node1");
        _registerNode(0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a, node2, "node2");
        _registerNode(0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6, node3, "node3");
        _registerNode(0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a, node4, "node4");
        _registerNode(0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba, node5, "node5");

        console.log("  5 nodes registered with 10k stake each");
        console.log("  Active node count:", registry.getActiveNodeCount());

        // Step 5: Register protocol
        console.log("");
        console.log("Step 5: Registering protocol...");

        vm.startBroadcast(0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e);
        token.approve(address(registry), PROTOCOL_STAKE);
        registry.registerProtocol(PROTOCOL_STAKE, 5_000_000 * 1e18, address(mockProtocol));

        // Deposit bounty
        token.approve(address(shield), 50_000 * 1e18);
        shield.depositBounty(50_000 * 1e18);
        vm.stopBroadcast();

        console.log("  Protocol registered with 25k stake");
        console.log("  Bounty deposited: 50k tokens");
        console.log("  Protocol pause target:", address(mockProtocol));

        // Step 6: Simulate attack detection and pause
        console.log("");
        console.log("Step 6: Simulating attack detection...");
        console.log("  Node1 detects suspicious transaction");

        vm.startBroadcast(0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d);
        bytes32 evidenceHash = keccak256("flash_loan_attack_evidence_hash");
        bytes32 requestId = router.createPauseRequest(protocolOwner, evidenceHash);
        vm.stopBroadcast();

        console.log("  Pause request created, ID:", vm.toString(requestId));
        console.log("  Signatures needed:", router.getRequiredSignatures());

        // Step 7: Nodes sign the pause request
        console.log("");
        console.log("Step 7: Nodes signing pause request...");

        vm.startBroadcast(0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a);
        router.signPauseRequest(requestId);
        vm.stopBroadcast();
        console.log("  Node2 signed (2/5)");

        vm.startBroadcast(0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6);
        router.signPauseRequest(requestId);
        vm.stopBroadcast();
        console.log("  Node3 signed (3/5)");

        vm.startBroadcast(0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a);
        router.signPauseRequest(requestId);
        vm.stopBroadcast();
        console.log("  Node4 signed (4/5)");

        console.log("");
        console.log("Step 8: Final signature triggers pause...");

        vm.startBroadcast(0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba);
        router.signPauseRequest(requestId);
        vm.stopBroadcast();
        console.log("  Node5 signed (5/5) - THRESHOLD REACHED!");

        // Step 9: Verify results
        console.log("");
        console.log("=== SIMULATION RESULTS ===");
        console.log("");

        bool protocolPaused = mockProtocol.paused();
        console.log("Protocol paused:", protocolPaused ? "YES" : "NO");

        (uint256 totalPauses, uint256 successfulPauses) = router.getStats();
        console.log("Total pause attempts:", totalPauses);
        console.log("Successful pauses:", successfulPauses);

        // Check bounty claim
        SentinelShield.BountyClaim memory claim = shield.getClaim(1);
        console.log("");
        console.log("Bounty Claim Details:");
        console.log("  Claim ID: 1");
        console.log("  Claiming node:", claim.node);
        console.log("  Target protocol:", claim.targetProtocol);
        console.log("  Bounty amount:", claim.bountyAmount / 1e6, "USDC-equivalent");
        console.log("  Status: PENDING (48h dispute window)");

        console.log("");
        console.log("=== SIMULATION COMPLETE ===");
        console.log("");
        console.log("Summary:");
        console.log("  - 5 nodes registered and staked");
        console.log("  - 1 protocol registered with bounty");
        console.log("  - Attack detected, pause request created");
        console.log("  - 5/5 signatures collected (threshold: 5)");
        console.log("  - Protocol successfully paused");
        console.log("  - Bounty claim created for node1");
    }

    function _registerNode(uint256 pk, address node, string memory name) internal {
        vm.startBroadcast(pk);
        token.approve(address(registry), MIN_NODE_STAKE);
        bytes32 blsKey = keccak256(abi.encodePacked("bls_key_", name));
        registry.registerNode(MIN_NODE_STAKE, blsKey);
        vm.stopBroadcast();
        console.log("  Registered", name, "at", node);
    }
}

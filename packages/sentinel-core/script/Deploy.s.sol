// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "forge-std/console.sol";
import "../src/SentinelToken.sol";
import "../src/SentinelRegistry.sol";
import "../src/SentinelShield.sol";
import "../src/SentinelRouter.sol";
import "../src/BLSVerifier.sol";
import "../src/TokenVesting.sol";

/**
 * @title Deploy
 * @notice Deploys all Sentinel Protocol contracts to testnet/mainnet
 * @dev Run with: forge script script/Deploy.s.sol --rpc-url $SEPOLIA_RPC_URL --broadcast --verify
 */
contract Deploy is Script {
    // Deployed contract addresses
    SentinelToken public token;
    SentinelRegistry public registry;
    SentinelShield public shield;
    SentinelRouter public router;
    BLSVerifier public blsVerifier;

    function run() external {
        // Load deployer private key from environment
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        // Oracle address (can be same as deployer for testnet)
        address oracle = vm.envOr("ORACLE_ADDRESS", deployer);

        console.log("=== SENTINEL PROTOCOL DEPLOYMENT ===");
        console.log("");
        console.log("Deployer:", deployer);
        console.log("Oracle:", oracle);
        console.log("Chain ID:", block.chainid);
        console.log("");

        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy SentinelToken
        console.log("1. Deploying SentinelToken...");
        token = new SentinelToken(deployer);
        console.log("   Address:", address(token));

        // 2. Deploy SentinelRegistry
        console.log("2. Deploying SentinelRegistry...");
        registry = new SentinelRegistry(address(token), deployer);
        console.log("   Address:", address(registry));

        // 3. Deploy BLSVerifier
        console.log("3. Deploying BLSVerifier...");
        blsVerifier = new BLSVerifier();
        console.log("   Address:", address(blsVerifier));

        // 4. Deploy SentinelShield
        console.log("4. Deploying SentinelShield...");
        shield = new SentinelShield(address(token), address(registry), deployer);
        console.log("   Address:", address(shield));

        // 5. Deploy SentinelRouter
        console.log("5. Deploying SentinelRouter...");
        router = new SentinelRouter(address(registry), address(shield), address(blsVerifier), deployer);
        console.log("   Address:", address(router));

        // 6. Configure contract relationships
        console.log("");
        console.log("6. Configuring contract relationships...");

        token.setRegistry(address(registry));
        console.log("   Token -> Registry: OK");

        registry.setRouter(address(router));
        console.log("   Registry -> Router: OK");

        registry.setShield(address(shield));
        console.log("   Registry -> Shield: OK");

        shield.setRouter(address(router));
        console.log("   Shield -> Router: OK");

        shield.setOracle(oracle);
        console.log("   Shield -> Oracle: OK");

        vm.stopBroadcast();

        // 7. Output deployment summary
        console.log("");
        console.log("=== DEPLOYMENT COMPLETE ===");
        console.log("");
        console.log("Add these to your .env file:");
        console.log("");
        console.log("SENTINEL_TOKEN_ADDRESS=", address(token));
        console.log("SENTINEL_REGISTRY_ADDRESS=", address(registry));
        console.log("SENTINEL_SHIELD_ADDRESS=", address(shield));
        console.log("SENTINEL_ROUTER_ADDRESS=", address(router));
        console.log("BLS_VERIFIER_ADDRESS=", address(blsVerifier));
        console.log("");

        // Write deployment addresses to file
        _writeDeploymentFile();
    }

    function _writeDeploymentFile() internal {
        string memory chainName = _getChainName();
        string memory json = string(abi.encodePacked(
            '{\n',
            '  "network": "', chainName, '",\n',
            '  "chainId": ', vm.toString(block.chainid), ',\n',
            '  "contracts": {\n',
            '    "SentinelToken": "', vm.toString(address(token)), '",\n',
            '    "SentinelRegistry": "', vm.toString(address(registry)), '",\n',
            '    "SentinelShield": "', vm.toString(address(shield)), '",\n',
            '    "SentinelRouter": "', vm.toString(address(router)), '",\n',
            '    "BLSVerifier": "', vm.toString(address(blsVerifier)), '"\n',
            '  },\n',
            '  "deployer": "', vm.toString(msg.sender), '",\n',
            '  "timestamp": ', vm.toString(block.timestamp), '\n',
            '}'
        ));

        string memory filename = string(abi.encodePacked("deployments/", chainName, ".json"));
        vm.writeFile(filename, json);
        console.log("Deployment saved to:", filename);
    }

    function _getChainName() internal view returns (string memory) {
        if (block.chainid == 1) return "mainnet";
        if (block.chainid == 11155111) return "sepolia";
        if (block.chainid == 31337) return "anvil";
        return vm.toString(block.chainid);
    }
}

/**
 * @title SetupTestnet
 * @notice Sets up testnet with test nodes and protocols after deployment
 * @dev Run after Deploy.s.sol
 */
contract SetupTestnet is Script {
    uint256 constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 constant PROTOCOL_STAKE = 25_000 * 1e18;
    uint256 constant BOUNTY_AMOUNT = 50_000 * 1e18;

    function run() external {
        // Load addresses from environment
        address tokenAddr = vm.envAddress("SENTINEL_TOKEN_ADDRESS");
        address registryAddr = vm.envAddress("SENTINEL_REGISTRY_ADDRESS");
        address shieldAddr = vm.envAddress("SENTINEL_SHIELD_ADDRESS");

        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        SentinelToken token = SentinelToken(tokenAddr);
        SentinelRegistry registry = SentinelRegistry(registryAddr);
        SentinelShield shield = SentinelShield(shieldAddr);

        console.log("=== TESTNET SETUP ===");
        console.log("");
        console.log("Token:", tokenAddr);
        console.log("Registry:", registryAddr);
        console.log("Shield:", shieldAddr);
        console.log("");

        vm.startBroadcast(deployerPrivateKey);

        // Register deployer as a node
        console.log("1. Registering deployer as node...");
        token.approve(address(registry), MIN_NODE_STAKE);
        bytes32 blsKey = keccak256(abi.encodePacked("testnet_node_", deployer));
        registry.registerNode(MIN_NODE_STAKE, blsKey);
        console.log("   Node registered with 10k SENTR stake");

        // Register as a test protocol
        console.log("2. Registering test protocol...");
        token.approve(address(registry), PROTOCOL_STAKE);
        registry.registerProtocol(PROTOCOL_STAKE, 1_000_000 * 1e18, deployer); // 1M TVL, self as pause target
        console.log("   Protocol registered with 25k SENTR stake");

        // Deposit bounty
        console.log("3. Depositing bounty...");
        token.approve(address(shield), BOUNTY_AMOUNT);
        shield.depositBounty(BOUNTY_AMOUNT);
        console.log("   Deposited 50k SENTR as bounty");

        vm.stopBroadcast();

        console.log("");
        console.log("=== SETUP COMPLETE ===");
        console.log("Active nodes:", registry.getActiveNodeCount());
    }
}

/**
 * @title DeployVesting
 * @notice Deploys vesting contracts and sets up token allocations
 * @dev Run after Deploy.s.sol for mainnet/testnet launches with proper tokenomics
 *
 * Token Allocation (100M total):
 * - Team:      20M (20%) - 4 year vest, 1 year cliff, revocable
 * - Investors: 15M (15%) - 2 year vest, 6 month cliff, non-revocable
 * - Ecosystem: 25M (25%) - 4 year vest, no cliff, revocable (grants)
 * - Treasury:  25M (25%) - No vesting, DAO controlled
 * - Public:    15M (15%) - No vesting, TGE liquidity
 */
contract DeployVesting is Script {
    // Allocation amounts (100M total supply)
    uint256 constant TEAM_ALLOCATION = 20_000_000 * 1e18;      // 20%
    uint256 constant INVESTOR_ALLOCATION = 15_000_000 * 1e18;  // 15%
    uint256 constant ECOSYSTEM_ALLOCATION = 25_000_000 * 1e18; // 25%
    uint256 constant TREASURY_ALLOCATION = 25_000_000 * 1e18;  // 25%
    uint256 constant PUBLIC_ALLOCATION = 15_000_000 * 1e18;    // 15%

    // Vesting durations
    uint64 constant ONE_YEAR = 365 days;
    uint64 constant TWO_YEARS = 2 * 365 days;
    uint64 constant FOUR_YEARS = 4 * 365 days;
    uint64 constant SIX_MONTHS = 180 days;

    // Deployed contracts
    TokenVesting public teamVesting;
    TokenVesting public investorVesting;
    TokenVesting public ecosystemVesting;

    function run() external {
        // Load configuration from environment
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        address tokenAddr = vm.envAddress("SENTINEL_TOKEN_ADDRESS");

        // Beneficiary addresses (set these in .env or use deployer as placeholder)
        address teamMultisig = vm.envOr("TEAM_MULTISIG", deployer);
        address treasuryMultisig = vm.envOr("TREASURY_MULTISIG", deployer);
        address publicSaleAddr = vm.envOr("PUBLIC_SALE_ADDRESS", deployer);

        SentinelToken token = SentinelToken(tokenAddr);

        console.log("=== VESTING DEPLOYMENT ===");
        console.log("");
        console.log("Token:", tokenAddr);
        console.log("Deployer:", deployer);
        console.log("Team Multisig:", teamMultisig);
        console.log("Treasury Multisig:", treasuryMultisig);
        console.log("");

        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy Team Vesting Contract
        console.log("1. Deploying Team Vesting Contract...");
        teamVesting = new TokenVesting(tokenAddr, deployer);
        console.log("   Address:", address(teamVesting));

        // 2. Deploy Investor Vesting Contract
        console.log("2. Deploying Investor Vesting Contract...");
        investorVesting = new TokenVesting(tokenAddr, deployer);
        console.log("   Address:", address(investorVesting));

        // 3. Deploy Ecosystem Vesting Contract (for grants)
        console.log("3. Deploying Ecosystem Vesting Contract...");
        ecosystemVesting = new TokenVesting(tokenAddr, deployer);
        console.log("   Address:", address(ecosystemVesting));

        // 4. Transfer tokens to vesting contracts
        console.log("");
        console.log("4. Transferring tokens to vesting contracts...");

        token.transfer(address(teamVesting), TEAM_ALLOCATION);
        console.log("   Team Vesting: 20M SENTR");

        token.transfer(address(investorVesting), INVESTOR_ALLOCATION);
        console.log("   Investor Vesting: 15M SENTR");

        token.transfer(address(ecosystemVesting), ECOSYSTEM_ALLOCATION);
        console.log("   Ecosystem Vesting: 25M SENTR");

        // 5. Transfer non-vesting allocations directly
        console.log("");
        console.log("5. Transferring non-vesting allocations...");

        token.transfer(treasuryMultisig, TREASURY_ALLOCATION);
        console.log("   Treasury (DAO): 25M SENTR");

        token.transfer(publicSaleAddr, PUBLIC_ALLOCATION);
        console.log("   Public/Liquidity: 15M SENTR");

        // 6. Create Team vesting schedule
        console.log("");
        console.log("6. Creating Team vesting schedule...");
        teamVesting.createVestingSchedule(
            teamMultisig,
            TEAM_ALLOCATION,
            uint64(block.timestamp),
            ONE_YEAR,      // 1 year cliff
            FOUR_YEARS,    // 4 year total vesting
            true           // revocable
        );
        console.log("   Team: 20M, 4yr vest, 1yr cliff, revocable");

        vm.stopBroadcast();

        // Output summary
        console.log("");
        console.log("=== VESTING DEPLOYMENT COMPLETE ===");
        console.log("");
        console.log("IMPORTANT: Add investor schedules manually:");
        console.log("  investorVesting.createVestingSchedule(");
        console.log("    investor_address,");
        console.log("    amount,");
        console.log("    start_time,");
        console.log("    180 days,  // 6 month cliff");
        console.log("    730 days,  // 2 year vesting");
        console.log("    false      // non-revocable");
        console.log("  )");
        console.log("");
        console.log("Deployed addresses:");
        console.log("TEAM_VESTING_ADDRESS=", address(teamVesting));
        console.log("INVESTOR_VESTING_ADDRESS=", address(investorVesting));
        console.log("ECOSYSTEM_VESTING_ADDRESS=", address(ecosystemVesting));
    }
}

/**
 * @title AddInvestorVesting
 * @notice Helper script to add individual investor vesting schedules
 * @dev Example: Add investor with 1M tokens, 2 year vest, 6 month cliff
 */
contract AddInvestorVesting is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");

        // Load investor vesting contract
        address vestingAddr = vm.envAddress("INVESTOR_VESTING_ADDRESS");

        // Load investor details (set in .env)
        address investor = vm.envAddress("INVESTOR_ADDRESS");
        uint256 amount = vm.envUint("INVESTOR_AMOUNT");

        TokenVesting vesting = TokenVesting(vestingAddr);

        console.log("=== ADD INVESTOR VESTING ===");
        console.log("");
        console.log("Vesting Contract:", vestingAddr);
        console.log("Investor:", investor);
        console.log("Amount:", amount / 1e18, "SENTR");

        vm.startBroadcast(deployerPrivateKey);

        vesting.createVestingSchedule(
            investor,
            amount,
            uint64(block.timestamp),
            180 days,   // 6 month cliff
            730 days,   // 2 year vesting
            false       // non-revocable
        );

        vm.stopBroadcast();

        console.log("");
        console.log("=== INVESTOR ADDED ===");
        console.log("Cliff ends:", block.timestamp + 180 days);
        console.log("Fully vested:", block.timestamp + 730 days);
    }
}

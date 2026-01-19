// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "forge-std/interfaces/IERC20.sol";
import {ReentrancyGuard} from "solmate/utils/ReentrancyGuard.sol";
import {Owned} from "solmate/auth/Owned.sol";
import {SentinelToken} from "./SentinelToken.sol";

contract SentinelRegistry is ReentrancyGuard, Owned {
    SentinelToken public immutable token;

    uint256 public constant MIN_NODE_STAKE = 10_000 * 1e18;
    uint256 public constant UNSTAKE_COOLDOWN = 21 days;
    uint256 public constant SLASH_FALSE_POSITIVE = 1000;
    uint256 public constant SLASH_DOWNTIME = 500;
    uint256 public constant SLASH_MALICIOUS = 10000;
    uint256 public constant BASIS_POINTS = 10000;

    uint256 public constant TVL_TIER_1 = 1_000_000 * 1e18;
    uint256 public constant TVL_TIER_2 = 10_000_000 * 1e18;
    uint256 public constant TVL_TIER_3 = 100_000_000 * 1e18;

    uint256 public constant STAKE_TIER_1 = 5_000 * 1e18;
    uint256 public constant STAKE_TIER_2 = 25_000 * 1e18;
    uint256 public constant STAKE_TIER_3 = 50_000 * 1e18;
    uint256 public constant STAKE_TIER_4 = 100_000 * 1e18;

    struct NodeInfo {
        uint256 stake;
        uint256 unstakeRequestTime;
        uint256 unstakeAmount;
        uint256 lastRewardClaim;
        uint256 totalRewardsClaimed;
        bool isActive;
        bytes32 blsPublicKey;
    }

    struct ProtocolInfo {
        uint256 stake;
        uint256 tvl;
        uint256 unstakeRequestTime;
        uint256 unstakeAmount;
        bool isActive;
        address pauseTarget;
    }

    mapping(address => NodeInfo) public nodes;
    mapping(address => ProtocolInfo) public protocols;

    address[] public activeNodes;
    address[] public activeProtocols;

    uint256 public totalNodeStake;
    uint256 public totalProtocolStake;
    uint256 public lastRewardDistribution;

    address public router;
    address public shield;

    error InsufficientStake();
    error NodeNotActive();
    error ProtocolNotActive();
    error CooldownNotComplete();
    error NoPendingUnstake();
    error Unauthorized();
    error InvalidBLSKey();
    error AlreadyRegistered();
    error ZeroAmount();

    event NodeRegistered(address indexed node, uint256 stake, bytes32 blsPublicKey);
    event NodeStakeIncreased(address indexed node, uint256 amount, uint256 newTotal);
    event NodeUnstakeRequested(address indexed node, uint256 amount);
    event NodeUnstakeCompleted(address indexed node, uint256 amount);
    event NodeSlashed(address indexed node, uint256 amount, string reason);
    event NodeDeactivated(address indexed node);

    event ProtocolRegistered(address indexed protocol, uint256 stake, address pauseTarget);
    event ProtocolStakeIncreased(address indexed protocol, uint256 amount);
    event ProtocolTVLUpdated(address indexed protocol, uint256 tvl);
    event ProtocolUnstakeRequested(address indexed protocol, uint256 amount);
    event ProtocolUnstakeCompleted(address indexed protocol, uint256 amount);
    event ProtocolDeactivated(address indexed protocol);

    event RewardsDistributed(uint256 totalAmount, uint256 nodeCount);
    event RewardClaimed(address indexed node, uint256 amount);

    constructor(address _token, address _owner) Owned(_owner) {
        token = SentinelToken(_token);
        lastRewardDistribution = block.timestamp;
    }

    function setRouter(address _router) external onlyOwner {
        router = _router;
    }

    function setShield(address _shield) external onlyOwner {
        shield = _shield;
    }

    function registerNode(uint256 stakeAmount, bytes32 blsPublicKey) external nonReentrant {
        if (stakeAmount < MIN_NODE_STAKE) revert InsufficientStake();
        if (blsPublicKey == bytes32(0)) revert InvalidBLSKey();
        if (nodes[msg.sender].isActive) revert AlreadyRegistered();

        token.transferFrom(msg.sender, address(this), stakeAmount);

        nodes[msg.sender] = NodeInfo({
            stake: stakeAmount,
            unstakeRequestTime: 0,
            unstakeAmount: 0,
            lastRewardClaim: block.timestamp,
            totalRewardsClaimed: 0,
            isActive: true,
            blsPublicKey: blsPublicKey
        });

        activeNodes.push(msg.sender);
        totalNodeStake += stakeAmount;

        emit NodeRegistered(msg.sender, stakeAmount, blsPublicKey);
    }

    function increaseNodeStake(uint256 amount) external nonReentrant {
        if (!nodes[msg.sender].isActive) revert NodeNotActive();
        if (amount == 0) revert ZeroAmount();

        token.transferFrom(msg.sender, address(this), amount);
        nodes[msg.sender].stake += amount;
        totalNodeStake += amount;

        emit NodeStakeIncreased(msg.sender, amount, nodes[msg.sender].stake);
    }

    function requestNodeUnstake(uint256 amount) external nonReentrant {
        NodeInfo storage node = nodes[msg.sender];
        if (!node.isActive) revert NodeNotActive();
        if (amount > node.stake) revert InsufficientStake();
        if (node.stake - amount < MIN_NODE_STAKE && amount != node.stake) revert InsufficientStake();

        node.unstakeRequestTime = block.timestamp;
        node.unstakeAmount = amount;

        emit NodeUnstakeRequested(msg.sender, amount);
    }

    function completeNodeUnstake() external nonReentrant {
        NodeInfo storage node = nodes[msg.sender];
        if (node.unstakeAmount == 0) revert NoPendingUnstake();
        if (block.timestamp < node.unstakeRequestTime + UNSTAKE_COOLDOWN) revert CooldownNotComplete();

        uint256 amount = node.unstakeAmount;
        node.stake -= amount;
        node.unstakeAmount = 0;
        node.unstakeRequestTime = 0;
        totalNodeStake -= amount;

        if (node.stake == 0) {
            node.isActive = false;
            _removeFromActiveNodes(msg.sender);
            emit NodeDeactivated(msg.sender);
        }

        token.transfer(msg.sender, amount);
        emit NodeUnstakeCompleted(msg.sender, amount);
    }

    function registerProtocol(uint256 stakeAmount, uint256 tvl, address pauseTarget) external nonReentrant {
        uint256 requiredStake = getRequiredProtocolStake(tvl);
        if (stakeAmount < requiredStake) revert InsufficientStake();
        if (protocols[msg.sender].isActive) revert AlreadyRegistered();

        token.transferFrom(msg.sender, address(this), stakeAmount);

        protocols[msg.sender] = ProtocolInfo({
            stake: stakeAmount,
            tvl: tvl,
            unstakeRequestTime: 0,
            unstakeAmount: 0,
            isActive: true,
            pauseTarget: pauseTarget
        });

        activeProtocols.push(msg.sender);
        totalProtocolStake += stakeAmount;

        emit ProtocolRegistered(msg.sender, stakeAmount, pauseTarget);
    }

    function updateProtocolTVL(uint256 newTVL) external {
        ProtocolInfo storage protocol = protocols[msg.sender];
        if (!protocol.isActive) revert ProtocolNotActive();

        uint256 requiredStake = getRequiredProtocolStake(newTVL);
        if (protocol.stake < requiredStake) revert InsufficientStake();

        protocol.tvl = newTVL;
        emit ProtocolTVLUpdated(msg.sender, newTVL);
    }

    function increaseProtocolStake(uint256 amount) external nonReentrant {
        if (!protocols[msg.sender].isActive) revert ProtocolNotActive();
        if (amount == 0) revert ZeroAmount();

        token.transferFrom(msg.sender, address(this), amount);
        protocols[msg.sender].stake += amount;
        totalProtocolStake += amount;

        emit ProtocolStakeIncreased(msg.sender, amount);
    }

    function requestProtocolUnstake(uint256 amount) external nonReentrant {
        ProtocolInfo storage protocol = protocols[msg.sender];
        if (!protocol.isActive) revert ProtocolNotActive();

        uint256 requiredStake = getRequiredProtocolStake(protocol.tvl);
        if (protocol.stake - amount < requiredStake && amount != protocol.stake) revert InsufficientStake();

        protocol.unstakeRequestTime = block.timestamp;
        protocol.unstakeAmount = amount;

        emit ProtocolUnstakeRequested(msg.sender, amount);
    }

    function completeProtocolUnstake() external nonReentrant {
        ProtocolInfo storage protocol = protocols[msg.sender];
        if (protocol.unstakeAmount == 0) revert NoPendingUnstake();
        if (block.timestamp < protocol.unstakeRequestTime + UNSTAKE_COOLDOWN) revert CooldownNotComplete();

        uint256 amount = protocol.unstakeAmount;
        protocol.stake -= amount;
        protocol.unstakeAmount = 0;
        protocol.unstakeRequestTime = 0;
        totalProtocolStake -= amount;

        if (protocol.stake == 0) {
            protocol.isActive = false;
            _removeFromActiveProtocols(msg.sender);
            emit ProtocolDeactivated(msg.sender);
        }

        token.transfer(msg.sender, amount);
        emit ProtocolUnstakeCompleted(msg.sender, amount);
    }

    function slashNode(address node, uint256 basisPoints, string calldata reason) external {
        if (msg.sender != router && msg.sender != shield && msg.sender != owner) revert Unauthorized();
        if (!nodes[node].isActive) revert NodeNotActive();

        uint256 slashAmount = (nodes[node].stake * basisPoints) / BASIS_POINTS;
        nodes[node].stake -= slashAmount;
        totalNodeStake -= slashAmount;

        token.burn(slashAmount);

        if (nodes[node].stake < MIN_NODE_STAKE) {
            nodes[node].isActive = false;
            _removeFromActiveNodes(node);
            emit NodeDeactivated(node);
        }

        emit NodeSlashed(node, slashAmount, reason);
    }

    function claimRewards() external nonReentrant {
        NodeInfo storage node = nodes[msg.sender];
        if (!node.isActive) revert NodeNotActive();

        uint256 pendingRewards = calculatePendingRewards(msg.sender);
        if (pendingRewards == 0) return;

        node.lastRewardClaim = block.timestamp;
        node.totalRewardsClaimed += pendingRewards;

        token.mint(msg.sender, pendingRewards);

        emit RewardClaimed(msg.sender, pendingRewards);
    }

    function calculatePendingRewards(address nodeAddress) public view returns (uint256) {
        NodeInfo storage node = nodes[nodeAddress];
        if (!node.isActive) return 0;

        uint256 timeSinceLastClaim = block.timestamp - node.lastRewardClaim;
        uint256 dailyReward = token.calculateDailyReward(totalProtocolStake);

        uint256 nodeShare = (node.stake * 1e18) / totalNodeStake;
        uint256 baseReward = (dailyReward * nodeShare) / 1e18;

        return (baseReward * timeSinceLastClaim) / 1 days;
    }

    function getRequiredProtocolStake(uint256 tvl) public pure returns (uint256) {
        if (tvl >= TVL_TIER_3) return STAKE_TIER_4;
        if (tvl >= TVL_TIER_2) return STAKE_TIER_3;
        if (tvl >= TVL_TIER_1) return STAKE_TIER_2;
        return STAKE_TIER_1;
    }

    function isNodeActive(address node) external view returns (bool) {
        return nodes[node].isActive;
    }

    function isProtocolActive(address protocol) external view returns (bool) {
        return protocols[protocol].isActive;
    }

    function getNodeStake(address node) external view returns (uint256) {
        return nodes[node].stake;
    }

    function getProtocolStake(address protocol) external view returns (uint256) {
        return protocols[protocol].stake;
    }

    function getActiveNodeCount() external view returns (uint256) {
        return activeNodes.length;
    }

    function getActiveProtocolCount() external view returns (uint256) {
        return activeProtocols.length;
    }

    function getActiveNodes() external view returns (address[] memory) {
        return activeNodes;
    }

    function getActiveProtocols() external view returns (address[] memory) {
        return activeProtocols;
    }

    function getProtocolPauseTarget(address protocol) external view returns (address) {
        return protocols[protocol].pauseTarget;
    }

    function _removeFromActiveNodes(address node) internal {
        for (uint256 i = 0; i < activeNodes.length; i++) {
            if (activeNodes[i] == node) {
                activeNodes[i] = activeNodes[activeNodes.length - 1];
                activeNodes.pop();
                break;
            }
        }
    }

    function _removeFromActiveProtocols(address protocol) internal {
        for (uint256 i = 0; i < activeProtocols.length; i++) {
            if (activeProtocols[i] == protocol) {
                activeProtocols[i] = activeProtocols[activeProtocols.length - 1];
                activeProtocols.pop();
                break;
            }
        }
    }
}

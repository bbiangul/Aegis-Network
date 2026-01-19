// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "solmate/tokens/ERC20.sol";
import {Owned} from "solmate/auth/Owned.sol";

contract SentinelToken is ERC20, Owned {
    address public registry;
    address public minter;

    uint256 public constant MAX_SUPPLY = 1_000_000_000 * 1e18;
    uint256 public constant INITIAL_SUPPLY = 100_000_000 * 1e18;

    uint256 public constant MIN_DAILY_REWARD = 5 * 1e18;
    uint256 public constant REWARD_NUMERATOR = 50 * 1e18;

    error Unauthorized();
    error ExceedsMaxSupply();
    error ZeroAddress();

    event MinterSet(address indexed minter);
    event RegistrySet(address indexed registry);
    event RewardsMinted(address indexed to, uint256 amount);
    event TokensBurned(address indexed from, uint256 amount);

    constructor(address _owner) ERC20("Sentinel Token", "SENTR", 18) Owned(_owner) {
        _mint(_owner, INITIAL_SUPPLY);
    }

    function setMinter(address _minter) external onlyOwner {
        if (_minter == address(0)) revert ZeroAddress();
        minter = _minter;
        emit MinterSet(_minter);
    }

    function setRegistry(address _registry) external onlyOwner {
        if (_registry == address(0)) revert ZeroAddress();
        registry = _registry;
        emit RegistrySet(_registry);
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != minter && msg.sender != registry) revert Unauthorized();
        if (totalSupply + amount > MAX_SUPPLY) revert ExceedsMaxSupply();
        _mint(to, amount);
        emit RewardsMinted(to, amount);
    }

    function burn(uint256 amount) external {
        _burn(msg.sender, amount);
        emit TokensBurned(msg.sender, amount);
    }

    function burnFrom(address from, uint256 amount) external {
        if (msg.sender != registry) revert Unauthorized();
        _burn(from, amount);
        emit TokensBurned(from, amount);
    }

    function calculateDailyReward(uint256 totalStakedTVL) public pure returns (uint256) {
        if (totalStakedTVL == 0) {
            return 100 * 1e18;
        }

        uint256 tvlInMillions = totalStakedTVL / 1e6;
        if (tvlInMillions == 0) {
            return 100 * 1e18;
        }

        uint256 sqrtTvl = sqrt(tvlInMillions);
        if (sqrtTvl == 0) sqrtTvl = 1;

        uint256 reward = REWARD_NUMERATOR / sqrtTvl;

        if (reward < MIN_DAILY_REWARD) {
            return MIN_DAILY_REWARD;
        }

        return reward;
    }

    function sqrt(uint256 x) internal pure returns (uint256) {
        if (x == 0) return 0;

        uint256 z = (x + 1) / 2;
        uint256 y = x;

        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }

        return y;
    }
}

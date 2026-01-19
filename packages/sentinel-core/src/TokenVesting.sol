// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "forge-std/interfaces/IERC20.sol";
import {Owned} from "solmate/auth/Owned.sol";
import {ReentrancyGuard} from "solmate/utils/ReentrancyGuard.sol";

/// @title TokenVesting
/// @notice Manages token vesting schedules with cliff and linear release
/// @dev Supports multiple beneficiaries with individual vesting schedules
contract TokenVesting is Owned, ReentrancyGuard {
    // ============ Structs ============

    struct VestingSchedule {
        uint256 totalAmount;      // Total tokens to vest
        uint256 released;         // Tokens already released
        uint64 startTime;         // Vesting start timestamp
        uint64 cliffDuration;     // Cliff duration in seconds
        uint64 vestingDuration;   // Total vesting duration (including cliff)
        bool revocable;           // Can be revoked by owner
        bool revoked;             // Has been revoked
    }

    // ============ State ============

    IERC20 public immutable token;

    mapping(address => VestingSchedule) public schedules;
    address[] public beneficiaries;

    uint256 public totalAllocated;
    uint256 public totalReleased;

    // ============ Events ============

    event VestingScheduleCreated(
        address indexed beneficiary,
        uint256 amount,
        uint64 startTime,
        uint64 cliffDuration,
        uint64 vestingDuration,
        bool revocable
    );
    event TokensReleased(address indexed beneficiary, uint256 amount);
    event VestingRevoked(address indexed beneficiary, uint256 amountRevoked);

    // ============ Errors ============

    error ZeroAddress();
    error ZeroAmount();
    error ScheduleExists();
    error ScheduleNotFound();
    error NotRevocable();
    error AlreadyRevoked();
    error NothingToRelease();
    error InsufficientBalance();
    error InvalidDuration();

    // ============ Constructor ============

    constructor(address _token, address _owner) Owned(_owner) {
        if (_token == address(0)) revert ZeroAddress();
        token = IERC20(_token);
    }

    // ============ Admin Functions ============

    /// @notice Create a vesting schedule for a beneficiary
    /// @param beneficiary Address that will receive vested tokens
    /// @param amount Total amount of tokens to vest
    /// @param startTime When vesting starts (can be in the past for retroactive vesting)
    /// @param cliffDuration Duration of cliff period in seconds
    /// @param vestingDuration Total vesting duration in seconds (must be >= cliffDuration)
    /// @param revocable Whether the schedule can be revoked
    function createVestingSchedule(
        address beneficiary,
        uint256 amount,
        uint64 startTime,
        uint64 cliffDuration,
        uint64 vestingDuration,
        bool revocable
    ) external onlyOwner {
        if (beneficiary == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (schedules[beneficiary].totalAmount > 0) revert ScheduleExists();
        if (vestingDuration < cliffDuration) revert InvalidDuration();
        if (vestingDuration == 0) revert InvalidDuration();

        // Ensure contract has enough tokens
        uint256 available = token.balanceOf(address(this)) - (totalAllocated - totalReleased);
        if (available < amount) revert InsufficientBalance();

        schedules[beneficiary] = VestingSchedule({
            totalAmount: amount,
            released: 0,
            startTime: startTime,
            cliffDuration: cliffDuration,
            vestingDuration: vestingDuration,
            revocable: revocable,
            revoked: false
        });

        beneficiaries.push(beneficiary);
        totalAllocated += amount;

        emit VestingScheduleCreated(
            beneficiary,
            amount,
            startTime,
            cliffDuration,
            vestingDuration,
            revocable
        );
    }

    /// @notice Revoke a vesting schedule (only for revocable schedules)
    /// @param beneficiary Address whose vesting to revoke
    function revoke(address beneficiary) external onlyOwner {
        VestingSchedule storage schedule = schedules[beneficiary];

        if (schedule.totalAmount == 0) revert ScheduleNotFound();
        if (!schedule.revocable) revert NotRevocable();
        if (schedule.revoked) revert AlreadyRevoked();

        // Calculate vested amount at revocation time
        uint256 vested = _vestedAmount(schedule);
        uint256 unreleased = vested - schedule.released;

        // Release any vested but unreleased tokens to beneficiary
        if (unreleased > 0) {
            schedule.released += unreleased;
            totalReleased += unreleased;
            token.transfer(beneficiary, unreleased);
            emit TokensReleased(beneficiary, unreleased);
        }

        // Calculate unvested amount to return to owner
        uint256 unvested = schedule.totalAmount - vested;
        schedule.revoked = true;

        if (unvested > 0) {
            totalAllocated -= unvested;
            token.transfer(owner, unvested);
        }

        emit VestingRevoked(beneficiary, unvested);
    }

    // ============ Beneficiary Functions ============

    /// @notice Release vested tokens to the caller
    function release() external nonReentrant {
        _release(msg.sender);
    }

    /// @notice Release vested tokens to a specific beneficiary
    /// @param beneficiary Address to release tokens to
    function releaseFor(address beneficiary) external nonReentrant {
        _release(beneficiary);
    }

    // ============ View Functions ============

    /// @notice Get the releasable amount for a beneficiary
    function releasable(address beneficiary) external view returns (uint256) {
        VestingSchedule storage schedule = schedules[beneficiary];
        if (schedule.revoked) return 0;
        return _vestedAmount(schedule) - schedule.released;
    }

    /// @notice Get the vested amount for a beneficiary
    function vestedAmount(address beneficiary) external view returns (uint256) {
        return _vestedAmount(schedules[beneficiary]);
    }

    /// @notice Get the unvested amount for a beneficiary
    function unvestedAmount(address beneficiary) external view returns (uint256) {
        VestingSchedule storage schedule = schedules[beneficiary];
        if (schedule.revoked) return 0;
        return schedule.totalAmount - _vestedAmount(schedule);
    }

    /// @notice Get the number of beneficiaries
    function beneficiaryCount() external view returns (uint256) {
        return beneficiaries.length;
    }

    /// @notice Check if cliff has passed for a beneficiary
    function cliffPassed(address beneficiary) external view returns (bool) {
        VestingSchedule storage schedule = schedules[beneficiary];
        return block.timestamp >= schedule.startTime + schedule.cliffDuration;
    }

    /// @notice Get time until cliff ends (0 if already passed)
    function timeUntilCliff(address beneficiary) external view returns (uint256) {
        VestingSchedule storage schedule = schedules[beneficiary];
        uint256 cliffEnd = schedule.startTime + schedule.cliffDuration;
        if (block.timestamp >= cliffEnd) return 0;
        return cliffEnd - block.timestamp;
    }

    /// @notice Get time until fully vested (0 if already fully vested)
    function timeUntilFullyVested(address beneficiary) external view returns (uint256) {
        VestingSchedule storage schedule = schedules[beneficiary];
        uint256 vestEnd = schedule.startTime + schedule.vestingDuration;
        if (block.timestamp >= vestEnd) return 0;
        return vestEnd - block.timestamp;
    }

    // ============ Internal Functions ============

    function _release(address beneficiary) internal {
        VestingSchedule storage schedule = schedules[beneficiary];

        if (schedule.totalAmount == 0) revert ScheduleNotFound();
        if (schedule.revoked) revert AlreadyRevoked();

        uint256 vested = _vestedAmount(schedule);
        uint256 unreleased = vested - schedule.released;

        if (unreleased == 0) revert NothingToRelease();

        schedule.released += unreleased;
        totalReleased += unreleased;

        token.transfer(beneficiary, unreleased);
        emit TokensReleased(beneficiary, unreleased);
    }

    function _vestedAmount(VestingSchedule storage schedule) internal view returns (uint256) {
        if (schedule.totalAmount == 0) return 0;
        if (schedule.revoked) return schedule.released;

        uint256 currentTime = block.timestamp;
        uint256 start = schedule.startTime;
        uint256 cliff = start + schedule.cliffDuration;
        uint256 end = start + schedule.vestingDuration;

        // Before cliff: nothing vested
        if (currentTime < cliff) {
            return 0;
        }

        // After full vesting: everything vested
        if (currentTime >= end) {
            return schedule.totalAmount;
        }

        // During vesting: linear release
        // Calculate time elapsed since start (not cliff)
        uint256 elapsed = currentTime - start;
        return (schedule.totalAmount * elapsed) / schedule.vestingDuration;
    }
}

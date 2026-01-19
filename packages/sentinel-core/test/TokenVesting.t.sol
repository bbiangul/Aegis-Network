// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/TokenVesting.sol";
import "../src/SentinelToken.sol";

contract TokenVestingTest is Test {
    SentinelToken public token;
    TokenVesting public vesting;

    address public owner = address(this);
    address public team = address(0x1);
    address public investor1 = address(0x2);
    address public investor2 = address(0x3);
    address public treasury = address(0x4);

    uint256 public constant INITIAL_SUPPLY = 100_000_000 * 1e18;

    // Vesting params
    uint64 public constant ONE_YEAR = 365 days;
    uint64 public constant TWO_YEARS = 2 * 365 days;
    uint64 public constant FOUR_YEARS = 4 * 365 days;
    uint64 public constant SIX_MONTHS = 180 days;

    function setUp() public {
        token = new SentinelToken(owner);
        vesting = new TokenVesting(address(token), owner);

        // Transfer tokens to vesting contract for allocation
        token.transfer(address(vesting), 50_000_000 * 1e18);
    }

    // ============ Creation Tests ============

    function test_CreateVestingSchedule() public {
        uint256 amount = 20_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,      // 1 year cliff
            FOUR_YEARS,    // 4 year total vesting
            true           // revocable
        );

        (
            uint256 totalAmount,
            uint256 released,
            uint64 start,
            uint64 cliff,
            uint64 duration,
            bool revocable,
            bool revoked
        ) = vesting.schedules(team);

        assertEq(totalAmount, amount);
        assertEq(released, 0);
        assertEq(start, startTime);
        assertEq(cliff, ONE_YEAR);
        assertEq(duration, FOUR_YEARS);
        assertTrue(revocable);
        assertFalse(revoked);
    }

    function test_CreateVestingSchedule_EmitsEvent() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vm.expectEmit(true, false, false, true);
        emit TokenVesting.VestingScheduleCreated(
            investor1,
            amount,
            startTime,
            SIX_MONTHS,
            TWO_YEARS,
            false
        );

        vesting.createVestingSchedule(
            investor1,
            amount,
            startTime,
            SIX_MONTHS,
            TWO_YEARS,
            false
        );
    }

    function test_CreateVestingSchedule_RevertsIfZeroAddress() public {
        vm.expectRevert(TokenVesting.ZeroAddress.selector);
        vesting.createVestingSchedule(
            address(0),
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );
    }

    function test_CreateVestingSchedule_RevertsIfZeroAmount() public {
        vm.expectRevert(TokenVesting.ZeroAmount.selector);
        vesting.createVestingSchedule(
            team,
            0,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );
    }

    function test_CreateVestingSchedule_RevertsIfScheduleExists() public {
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.expectRevert(TokenVesting.ScheduleExists.selector);
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );
    }

    function test_CreateVestingSchedule_RevertsIfInsufficientBalance() public {
        vm.expectRevert(TokenVesting.InsufficientBalance.selector);
        vesting.createVestingSchedule(
            team,
            100_000_000 * 1e18, // More than available
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );
    }

    function test_CreateVestingSchedule_RevertsIfInvalidDuration() public {
        vm.expectRevert(TokenVesting.InvalidDuration.selector);
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            FOUR_YEARS,  // Cliff longer than vesting
            ONE_YEAR,
            true
        );
    }

    // ============ Cliff Tests ============

    function test_NothingReleasableBeforeCliff() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Warp to just before cliff
        vm.warp(block.timestamp + ONE_YEAR - 1);

        assertEq(vesting.releasable(team), 0);
        assertEq(vesting.vestedAmount(team), 0);
        assertFalse(vesting.cliffPassed(team));
    }

    function test_CliffPassed() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Warp to exactly cliff
        vm.warp(block.timestamp + ONE_YEAR);

        assertTrue(vesting.cliffPassed(team));
        assertGt(vesting.vestedAmount(team), 0);
    }

    function test_TimeUntilCliff() public {
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        assertEq(vesting.timeUntilCliff(team), ONE_YEAR);

        vm.warp(block.timestamp + SIX_MONTHS);
        assertEq(vesting.timeUntilCliff(team), ONE_YEAR - SIX_MONTHS);

        vm.warp(block.timestamp + ONE_YEAR);
        assertEq(vesting.timeUntilCliff(team), 0);
    }

    // ============ Linear Vesting Tests ============

    function test_LinearVestingAfterCliff() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // At cliff (1 year): 25% vested
        vm.warp(block.timestamp + ONE_YEAR);
        uint256 vestedAtCliff = vesting.vestedAmount(team);
        assertEq(vestedAtCliff, amount / 4); // 25%

        // At 2 years: 50% vested
        vm.warp(startTime + TWO_YEARS);
        uint256 vestedAt2Years = vesting.vestedAmount(team);
        assertEq(vestedAt2Years, amount / 2); // 50%

        // At 3 years: 75% vested
        vm.warp(startTime + 3 * 365 days);
        uint256 vestedAt3Years = vesting.vestedAmount(team);
        assertEq(vestedAt3Years, (amount * 3) / 4); // 75%

        // At 4 years: 100% vested
        vm.warp(startTime + FOUR_YEARS);
        uint256 vestedAt4Years = vesting.vestedAmount(team);
        assertEq(vestedAt4Years, amount); // 100%
    }

    function test_FullyVestedAfterDuration() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Warp past vesting period
        vm.warp(block.timestamp + FOUR_YEARS + 1 days);

        assertEq(vesting.vestedAmount(team), amount);
        assertEq(vesting.unvestedAmount(team), 0);
        assertEq(vesting.timeUntilFullyVested(team), 0);
    }

    // ============ Release Tests ============

    function test_Release() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Warp to 2 years (50% vested)
        vm.warp(startTime + TWO_YEARS);

        uint256 expectedRelease = amount / 2;
        uint256 balanceBefore = token.balanceOf(team);

        vm.prank(team);
        vesting.release();

        assertEq(token.balanceOf(team), balanceBefore + expectedRelease);
        assertEq(vesting.releasable(team), 0);
    }

    function test_Release_EmitsEvent() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.warp(startTime + TWO_YEARS);

        vm.expectEmit(true, false, false, true);
        emit TokenVesting.TokensReleased(team, amount / 2);

        vm.prank(team);
        vesting.release();
    }

    function test_Release_RevertsIfNothingToRelease() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Still in cliff period
        vm.prank(team);
        vm.expectRevert(TokenVesting.NothingToRelease.selector);
        vesting.release();
    }

    function test_ReleaseFor() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.warp(startTime + TWO_YEARS);

        // Anyone can call releaseFor
        vm.prank(investor1);
        vesting.releaseFor(team);

        assertEq(token.balanceOf(team), amount / 2);
    }

    function test_MultipleReleases() public {
        uint256 amount = 12_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // First release at 1 year (25% vested)
        vm.warp(startTime + ONE_YEAR);
        vm.prank(team);
        vesting.release();
        uint256 balanceAfterYear1 = token.balanceOf(team);
        assertGt(balanceAfterYear1, 0);

        // Second release at 2 years (50% vested)
        vm.warp(startTime + TWO_YEARS);
        vm.prank(team);
        vesting.release();
        uint256 balanceAfterYear2 = token.balanceOf(team);
        assertGt(balanceAfterYear2, balanceAfterYear1);

        // Third release at 4 years (100% vested)
        vm.warp(startTime + FOUR_YEARS);
        vm.prank(team);
        vesting.release();
        assertEq(token.balanceOf(team), amount);
    }

    // ============ Revoke Tests ============

    function test_Revoke() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Revoke at 2 years (50% vested)
        vm.warp(startTime + TWO_YEARS);

        uint256 ownerBalanceBefore = token.balanceOf(owner);

        vesting.revoke(team);

        // Team gets vested portion
        assertEq(token.balanceOf(team), amount / 2);

        // Owner gets unvested portion back
        assertEq(token.balanceOf(owner), ownerBalanceBefore + amount / 2);

        // Schedule is revoked
        (,,,,,, bool revoked) = vesting.schedules(team);
        assertTrue(revoked);
    }

    function test_Revoke_RevertsIfNotRevocable() public {
        vesting.createVestingSchedule(
            investor1,
            1000 * 1e18,
            uint64(block.timestamp),
            SIX_MONTHS,
            TWO_YEARS,
            false // not revocable
        );

        vm.expectRevert(TokenVesting.NotRevocable.selector);
        vesting.revoke(investor1);
    }

    function test_Revoke_RevertsIfAlreadyRevoked() public {
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.warp(block.timestamp + TWO_YEARS);
        vesting.revoke(team);

        vm.expectRevert(TokenVesting.AlreadyRevoked.selector);
        vesting.revoke(team);
    }

    function test_Revoke_BeforeCliff() public {
        uint256 amount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(
            team,
            amount,
            startTime,
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        // Revoke before cliff
        vm.warp(startTime + SIX_MONTHS);

        uint256 ownerBalanceBefore = token.balanceOf(owner);
        vesting.revoke(team);

        // Team gets nothing (still in cliff)
        assertEq(token.balanceOf(team), 0);

        // Owner gets everything back
        assertEq(token.balanceOf(owner), ownerBalanceBefore + amount);
    }

    function test_Release_RevertsAfterRevoked() public {
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.warp(block.timestamp + TWO_YEARS);
        vesting.revoke(team);

        vm.prank(team);
        vm.expectRevert(TokenVesting.AlreadyRevoked.selector);
        vesting.release();
    }

    // ============ View Function Tests ============

    function test_BeneficiaryCount() public {
        assertEq(vesting.beneficiaryCount(), 0);

        vesting.createVestingSchedule(team, 1000 * 1e18, uint64(block.timestamp), ONE_YEAR, FOUR_YEARS, true);
        assertEq(vesting.beneficiaryCount(), 1);

        vesting.createVestingSchedule(investor1, 500 * 1e18, uint64(block.timestamp), SIX_MONTHS, TWO_YEARS, false);
        assertEq(vesting.beneficiaryCount(), 2);
    }

    function test_TotalAllocatedAndReleased() public {
        uint256 teamAmount = 20_000_000 * 1e18;
        uint256 investorAmount = 10_000_000 * 1e18;
        uint64 startTime = uint64(block.timestamp);

        vesting.createVestingSchedule(team, teamAmount, startTime, ONE_YEAR, FOUR_YEARS, true);
        vesting.createVestingSchedule(investor1, investorAmount, startTime, SIX_MONTHS, TWO_YEARS, false);

        assertEq(vesting.totalAllocated(), teamAmount + investorAmount);
        assertEq(vesting.totalReleased(), 0);

        // Release some tokens
        vm.warp(startTime + ONE_YEAR);

        vm.prank(team);
        vesting.release();

        vm.prank(investor1);
        vesting.release();

        assertGt(vesting.totalReleased(), 0);
    }

    // ============ Access Control Tests ============

    function test_OnlyOwnerCanCreateSchedule() public {
        vm.prank(team);
        vm.expectRevert("UNAUTHORIZED");
        vesting.createVestingSchedule(
            investor1,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );
    }

    function test_OnlyOwnerCanRevoke() public {
        vesting.createVestingSchedule(
            team,
            1000 * 1e18,
            uint64(block.timestamp),
            ONE_YEAR,
            FOUR_YEARS,
            true
        );

        vm.prank(team);
        vm.expectRevert("UNAUTHORIZED");
        vesting.revoke(team);
    }

    // ============ Integration Test ============

    function test_FullVestingScenario() public {
        uint64 startTime = uint64(block.timestamp);

        // Setup: Create vesting schedules for team and investors
        // Team: 20M, 4 year vest, 1 year cliff, revocable
        vesting.createVestingSchedule(team, 20_000_000 * 1e18, startTime, ONE_YEAR, FOUR_YEARS, true);

        // Investor 1: 10M, 2 year vest, 6 month cliff, non-revocable
        vesting.createVestingSchedule(investor1, 10_000_000 * 1e18, startTime, SIX_MONTHS, TWO_YEARS, false);

        // Investor 2: 5M, 2 year vest, 6 month cliff, non-revocable
        vesting.createVestingSchedule(investor2, 5_000_000 * 1e18, startTime, SIX_MONTHS, TWO_YEARS, false);

        // Month 6: Investor cliff ends, can claim
        // Note: 180 days / 730 days = ~24.66% (not exactly 25% due to day calculation)
        vm.warp(startTime + SIX_MONTHS);
        assertFalse(vesting.cliffPassed(team));
        assertTrue(vesting.cliffPassed(investor1));

        vm.prank(investor1);
        vesting.release();
        // Verify investor got tokens (approximately 24.66% at 6 months)
        assertGt(token.balanceOf(investor1), 2_400_000 * 1e18);
        assertLt(token.balanceOf(investor1), 2_600_000 * 1e18);

        // Year 1: Team cliff ends, can claim 25%
        vm.warp(startTime + ONE_YEAR);
        assertTrue(vesting.cliffPassed(team));

        vm.prank(team);
        vesting.release();
        uint256 teamBalanceYear1 = token.balanceOf(team);
        assertGt(teamBalanceYear1, 0); // Team has received tokens

        // Year 2: Team at 50%, investors fully vested
        vm.warp(startTime + TWO_YEARS);

        vm.prank(team);
        vesting.release();
        uint256 teamBalanceYear2 = token.balanceOf(team);
        assertGt(teamBalanceYear2, teamBalanceYear1); // Team has received more tokens

        vm.prank(investor1);
        vesting.release();
        assertEq(token.balanceOf(investor1), 10_000_000 * 1e18); // 100% of 10M

        vm.prank(investor2);
        vesting.release();
        assertEq(token.balanceOf(investor2), 5_000_000 * 1e18); // 100% of 5M

        // Year 4: Team fully vested
        vm.warp(startTime + FOUR_YEARS);

        vm.prank(team);
        vesting.release();
        assertEq(token.balanceOf(team), 20_000_000 * 1e18); // 100% of 20M
    }
}

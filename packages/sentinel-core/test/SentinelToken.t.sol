// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SentinelToken.sol";

contract SentinelTokenTest is Test {
    SentinelToken public token;

    address public owner = address(0x1);
    address public minter = address(0x2);
    address public registry = address(0x3);
    address public user1 = address(0x4);
    address public user2 = address(0x5);

    function setUp() public {
        vm.prank(owner);
        token = new SentinelToken(owner);
    }

    // ============ Constructor Tests ============

    function test_InitialSupply() public view {
        assertEq(token.totalSupply(), token.INITIAL_SUPPLY());
        assertEq(token.balanceOf(owner), token.INITIAL_SUPPLY());
    }

    function test_TokenMetadata() public view {
        assertEq(token.name(), "Sentinel Token");
        assertEq(token.symbol(), "SENTR");
        assertEq(token.decimals(), 18);
    }

    function test_OwnerIsSet() public view {
        assertEq(token.owner(), owner);
    }

    // ============ Minter/Registry Setup Tests ============

    function test_SetMinter() public {
        vm.prank(owner);
        token.setMinter(minter);
        assertEq(token.minter(), minter);
    }

    function test_SetMinter_EmitsEvent() public {
        vm.prank(owner);
        vm.expectEmit(true, false, false, false);
        emit SentinelToken.MinterSet(minter);
        token.setMinter(minter);
    }

    function test_SetMinter_RevertsIfNotOwner() public {
        vm.prank(user1);
        vm.expectRevert("UNAUTHORIZED");
        token.setMinter(minter);
    }

    function test_SetMinter_RevertsIfZeroAddress() public {
        vm.prank(owner);
        vm.expectRevert(SentinelToken.ZeroAddress.selector);
        token.setMinter(address(0));
    }

    function test_SetRegistry() public {
        vm.prank(owner);
        token.setRegistry(registry);
        assertEq(token.registry(), registry);
    }

    function test_SetRegistry_RevertsIfZeroAddress() public {
        vm.prank(owner);
        vm.expectRevert(SentinelToken.ZeroAddress.selector);
        token.setRegistry(address(0));
    }

    // ============ Mint Tests ============

    function test_Mint_ByMinter() public {
        vm.prank(owner);
        token.setMinter(minter);

        uint256 mintAmount = 1000 * 1e18;
        vm.prank(minter);
        token.mint(user1, mintAmount);

        assertEq(token.balanceOf(user1), mintAmount);
    }

    function test_Mint_ByRegistry() public {
        vm.prank(owner);
        token.setRegistry(registry);

        uint256 mintAmount = 1000 * 1e18;
        vm.prank(registry);
        token.mint(user1, mintAmount);

        assertEq(token.balanceOf(user1), mintAmount);
    }

    function test_Mint_RevertsIfUnauthorized() public {
        vm.prank(user1);
        vm.expectRevert(SentinelToken.Unauthorized.selector);
        token.mint(user1, 1000 * 1e18);
    }

    function test_Mint_RevertsIfExceedsMaxSupply() public {
        vm.prank(owner);
        token.setMinter(minter);

        uint256 remaining = token.MAX_SUPPLY() - token.totalSupply();

        vm.prank(minter);
        vm.expectRevert(SentinelToken.ExceedsMaxSupply.selector);
        token.mint(user1, remaining + 1);
    }

    function test_Mint_EmitsEvent() public {
        vm.prank(owner);
        token.setMinter(minter);

        uint256 mintAmount = 1000 * 1e18;
        vm.prank(minter);
        vm.expectEmit(true, false, false, true);
        emit SentinelToken.RewardsMinted(user1, mintAmount);
        token.mint(user1, mintAmount);
    }

    // ============ Burn Tests ============

    function test_Burn() public {
        uint256 burnAmount = 100 * 1e18;
        uint256 initialBalance = token.balanceOf(owner);

        vm.prank(owner);
        token.burn(burnAmount);

        assertEq(token.balanceOf(owner), initialBalance - burnAmount);
        assertEq(token.totalSupply(), token.INITIAL_SUPPLY() - burnAmount);
    }

    function test_Burn_EmitsEvent() public {
        uint256 burnAmount = 100 * 1e18;

        vm.prank(owner);
        vm.expectEmit(true, false, false, true);
        emit SentinelToken.TokensBurned(owner, burnAmount);
        token.burn(burnAmount);
    }

    function test_BurnFrom_ByRegistry() public {
        // Transfer tokens to user first
        vm.prank(owner);
        token.transfer(user1, 1000 * 1e18);

        vm.prank(owner);
        token.setRegistry(registry);

        uint256 burnAmount = 100 * 1e18;
        uint256 initialBalance = token.balanceOf(user1);

        vm.prank(registry);
        token.burnFrom(user1, burnAmount);

        assertEq(token.balanceOf(user1), initialBalance - burnAmount);
    }

    function test_BurnFrom_RevertsIfNotRegistry() public {
        vm.prank(owner);
        token.transfer(user1, 1000 * 1e18);

        vm.prank(user2);
        vm.expectRevert(SentinelToken.Unauthorized.selector);
        token.burnFrom(user1, 100 * 1e18);
    }

    // ============ Transfer Tests ============

    function test_Transfer() public {
        uint256 transferAmount = 1000 * 1e18;

        vm.prank(owner);
        token.transfer(user1, transferAmount);

        assertEq(token.balanceOf(user1), transferAmount);
    }

    function test_TransferFrom() public {
        uint256 transferAmount = 1000 * 1e18;

        vm.prank(owner);
        token.approve(user1, transferAmount);

        vm.prank(user1);
        token.transferFrom(owner, user2, transferAmount);

        assertEq(token.balanceOf(user2), transferAmount);
    }

    // ============ Daily Reward Calculation Tests ============

    function test_CalculateDailyReward_ZeroTVL() public view {
        uint256 reward = token.calculateDailyReward(0);
        assertEq(reward, 100 * 1e18);
    }

    function test_CalculateDailyReward_SmallTVL() public view {
        uint256 reward = token.calculateDailyReward(100_000); // Less than 1M
        assertEq(reward, 100 * 1e18);
    }

    function test_CalculateDailyReward_LargeTVL() public view {
        // With very large TVL, reward should approach MIN_DAILY_REWARD
        uint256 reward = token.calculateDailyReward(1_000_000_000 * 1e6); // 1B
        assertGe(reward, token.MIN_DAILY_REWARD());
    }

    function test_CalculateDailyReward_NeverBelowMinimum() public view {
        uint256 reward = token.calculateDailyReward(type(uint256).max / 2);
        assertGe(reward, token.MIN_DAILY_REWARD());
    }

    // ============ Fuzz Tests ============

    function testFuzz_Mint(uint256 amount) public {
        vm.assume(amount > 0);
        vm.assume(amount <= token.MAX_SUPPLY() - token.totalSupply());

        vm.prank(owner);
        token.setMinter(minter);

        vm.prank(minter);
        token.mint(user1, amount);

        assertEq(token.balanceOf(user1), amount);
    }

    function testFuzz_Transfer(uint256 amount) public {
        vm.assume(amount > 0);
        vm.assume(amount <= token.balanceOf(owner));

        vm.prank(owner);
        token.transfer(user1, amount);

        assertEq(token.balanceOf(user1), amount);
    }

    function testFuzz_DailyReward(uint256 tvl) public view {
        vm.assume(tvl < type(uint256).max / 2);

        uint256 reward = token.calculateDailyReward(tvl);
        assertGe(reward, token.MIN_DAILY_REWARD());
    }
}

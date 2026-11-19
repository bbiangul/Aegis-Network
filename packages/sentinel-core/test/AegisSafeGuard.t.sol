// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import { Safe } from "safe/Safe.sol";
import { SafeProxyFactory } from "safe/proxies/SafeProxyFactory.sol";
import { MultiSendCallOnly } from "safe/libraries/MultiSendCallOnly.sol";
import { CompatibilityFallbackHandler } from "safe/handler/CompatibilityFallbackHandler.sol";
import { Enum } from "safe/common/Enum.sol";
import { ERC20 } from "solmate/tokens/ERC20.sol";

import { AegisSafeGuard } from "../src/guard/AegisSafeGuard.sol";
import { ThresholdAttester } from "../src/guard/ThresholdAttester.sol";

interface IERC1271 {
    function isValidSignature(bytes32 hash, bytes calldata signature) external view returns (bytes4);
}

contract MockToken is ERC20 {
    constructor() ERC20("Mock USD", "mUSD", 6) { }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function permitDigest(address owner, address spender, uint256 value) public view returns (bytes32) {
        return keccak256(abi.encode("permit", address(this), owner, spender, value));
    }

    /// @dev Like USDC v2.2: a contract owner authorises a permit through ERC-1271, with no transaction of its own.
    function permit1271(address owner, address spender, uint256 value, bytes calldata signature) external {
        require(
            IERC1271(owner).isValidSignature(permitDigest(owner, spender, value), signature) == 0x1626ba7e, "bad sig"
        );
        allowance[owner][spender] = value;
    }
}

/// @dev Run via delegatecall. Same shape as the Bybit payload: overwrite slot 0, the proxy's singleton pointer.
contract SingletonSwapper {
    function swap(address newSingleton) external {
        assembly {
            sstore(0, newSingleton)
        }
    }
}

contract Backdoor {
    function sweep(address payable to) external {
        to.transfer(address(this).balance);
    }
}

contract DummyModule { }

contract AegisSafeGuardTest is Test {
    uint32 constant DELAY = 24 hours;
    uint32 constant EXPEDITED = 10 minutes;
    uint32 constant WINDOW = 24 hours;
    uint128 constant ETH_LIMIT = 10 ether;
    uint128 constant TOKEN_LIMIT = 50_000e6;

    Safe singleton;
    SafeProxyFactory factory;
    CompatibilityFallbackHandler handler;
    MultiSendCallOnly multiSend;
    MockToken token;
    AegisSafeGuard guard;
    ThresholdAttester attester;

    Safe safe;

    address[] owners;
    uint256[] ownerKeys;
    address[] attesters;
    uint256[] attesterKeys;

    address recipient = makeAddr("recipient");
    address attacker = makeAddr("attacker");

    function setUp() public {
        vm.warp(1_700_000_000);

        (owners, ownerKeys) = _sortedKeys("owner", 3);
        (attesters, attesterKeys) = _sortedKeys("attester", 3);

        singleton = new Safe();
        factory = new SafeProxyFactory();
        handler = new CompatibilityFallbackHandler();
        multiSend = new MultiSendCallOnly();
        token = new MockToken();
        guard = new AegisSafeGuard();
        attester = new ThresholdAttester(attesters, 2);

        safe = _deploySafe(address(handler), 1);
        _installGuard(safe, false);
    }

    // ---------------------------------------------------------------------------------------------
    // Layer 1: outflow budget
    // ---------------------------------------------------------------------------------------------

    function test_installed() public view {
        assertTrue(guard.isProtected(address(safe)));
        assertEq(guard.trackedAssets(address(safe)).length, 2);
    }

    function test_transferWithinBudget_passesWithoutAnyAttester() public {
        _exec(safe, recipient, 5 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 5 ether);
        assertEq(guard.available(address(safe), address(0)), 5 ether);

        _exec(safe, address(token), 0, abi.encodeCall(token.transfer, (recipient, 20_000e6)), Enum.Operation.Call);
        assertEq(token.balanceOf(recipient), 20_000e6);
    }

    function test_ethAboveBudget_reverts() public {
        _execRevert(_needsSchedule(recipient, 11 ether, "", Enum.Operation.Call), safe, recipient, 11 ether, "", Enum.Operation.Call);
    }

    function test_tokenAboveBudget_reverts() public {
        bytes memory data = abi.encodeCall(token.transfer, (attacker, 1_000_000e6));
        _execRevert(_needsSchedule(address(token), 0, data, Enum.Operation.Call), safe, address(token), 0, data, Enum.Operation.Call);
        assertEq(token.balanceOf(attacker), 0);
    }

    function test_budgetAccumulatesAndRefills() public {
        _exec(safe, recipient, 6 ether, "", Enum.Operation.Call);
        // 6 spent, 4 left: a second 6 does not fit
        _execRevert(_needsSchedule(recipient, 6 ether, "", Enum.Operation.Call), safe, recipient, 6 ether, "", Enum.Operation.Call);

        vm.warp(block.timestamp + 12 hours); // half the window refills half the limit
        assertEq(guard.available(address(safe), address(0)), 9 ether);
        _exec(safe, recipient, 6 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 12 ether);
    }

    function test_drainInSmallSteps_isCappedByBudget() public {
        // A thief with the keys can take the budget, and only the budget, per window.
        for (uint256 i = 0; i < 10; i++) {
            _exec(safe, attacker, 1 ether, "", Enum.Operation.Call);
        }
        _execRevert(_needsSchedule(attacker, 1 ether, "", Enum.Operation.Call), safe, attacker, 1 ether, "", Enum.Operation.Call);
        assertEq(attacker.balance, 10 ether);
        assertEq(address(safe).balance, 990 ether);
    }

    // ---------------------------------------------------------------------------------------------
    // Layer 1: Bybit-style singleton swap
    // ---------------------------------------------------------------------------------------------

    function test_bybitReplay_unguardedSafeIsDrained() public {
        Safe victim = _deploySafe(address(handler), 2);
        SingletonSwapper swapper = new SingletonSwapper();
        Backdoor backdoor = new Backdoor();

        // Owners sign what their UI shows as a routine transaction; it is really a delegatecall.
        _exec(victim, address(swapper), 0, abi.encodeCall(swapper.swap, (address(backdoor))), Enum.Operation.DelegateCall);

        Backdoor(address(victim)).sweep(payable(attacker));
        assertEq(attacker.balance, 1000 ether);
    }

    function test_bybitReplay_guardBlocksSingletonSwap() public {
        SingletonSwapper swapper = new SingletonSwapper();
        Backdoor backdoor = new Backdoor();
        bytes memory data = abi.encodeCall(swapper.swap, (address(backdoor)));

        // Same validly signed transaction. No detection, no network, no ML involved.
        _execRevert(
            _needsSchedule(address(swapper), 0, data, Enum.Operation.DelegateCall),
            safe,
            address(swapper),
            0,
            data,
            Enum.Operation.DelegateCall
        );
        assertEq(address(safe).balance, 1000 ether);
        assertEq(safe.getOwners().length, 3);
    }

    function test_configChanges_requireSchedule() public {
        bytes[] memory calls = new bytes[](6);
        calls[0] = abi.encodeCall(safe.addOwnerWithThreshold, (attacker, 1));
        calls[1] = abi.encodeCall(safe.changeThreshold, (1));
        calls[2] = abi.encodeCall(safe.setGuard, (address(0)));
        calls[3] = abi.encodeCall(safe.enableModule, (address(new DummyModule())));
        calls[4] = abi.encodeCall(safe.setFallbackHandler, (address(0)));
        calls[5] = abi.encodeCall(safe.swapOwner, (owners[0], owners[1], attacker));

        for (uint256 i = 0; i < calls.length; i++) {
            _execRevert(
                _needsSchedule(address(safe), 0, calls[i], Enum.Operation.Call),
                safe,
                address(safe),
                0,
                calls[i],
                Enum.Operation.Call
            );
        }
        assertTrue(guard.isProtected(address(safe)));
    }

    function test_looseningPolicy_requiresSchedule() public {
        bytes memory data = _configureCall(false, type(uint128).max, type(uint128).max);
        _execRevert(_needsSchedule(address(guard), 0, data, Enum.Operation.Call), safe, address(guard), 0, data, Enum.Operation.Call);

        _schedule(address(guard), 0, data, Enum.Operation.Call);
        vm.warp(block.timestamp + DELAY);
        _exec(safe, address(guard), 0, data, Enum.Operation.Call);
        assertEq(guard.available(address(safe), address(0)), type(uint128).max);
    }

    function test_gasRefund_isBlocked() public {
        // Refund parameters would pay `attacker` out of the Safe without appearing in `to`/`value`/`data`.
        bytes32 hash =
            safe.getTransactionHash(recipient, 0, "", Enum.Operation.Call, 100_000, 100_000, 1 gwei, address(0), payable(attacker), safe.nonce());
        bytes memory sigs = _signOwners(hash);
        vm.expectRevert(AegisSafeGuard.RefundNotAllowed.selector);
        safe.execTransaction(recipient, 0, "", Enum.Operation.Call, 100_000, 100_000, 1 gwei, address(0), payable(attacker), sigs);
    }

    function test_nestedExecution_cannotHideOutflow() public {
        // Batch: [send 500 ETH out, then run a harmless inner Safe transaction]. Without the nesting lock the
        // inner transaction would re-snapshot balances after the transfer and clear the outer context.
        // The inner tx is signed for the nonce it will see once the outer one has started.
        bytes32 innerHash =
            safe.getTransactionHash(recipient, 0, "", Enum.Operation.Call, 0, 0, 0, address(0), payable(0), safe.nonce() + 1);
        bytes memory inner = abi.encodeCall(
            safe.execTransaction,
            (recipient, 0, "", Enum.Operation.Call, 0, 0, 0, address(0), payable(0), _signOwners(innerHash))
        );
        bytes memory batch = abi.encodePacked(_packed(attacker, 500 ether, ""), _packed(address(safe), 0, inner));

        _execRevert(
            bytes("GS013"), safe, address(multiSend), 0, abi.encodeCall(multiSend.multiSend, (batch)), Enum.Operation.DelegateCall
        );
        assertEq(attacker.balance, 0);
    }

    // ---------------------------------------------------------------------------------------------
    // Layer 1: approvals and batches
    // ---------------------------------------------------------------------------------------------

    function test_approve_requiresSchedule() public {
        bytes memory data = abi.encodeCall(token.approve, (attacker, type(uint256).max));
        _execRevert(_needsSchedule(address(token), 0, data, Enum.Operation.Call), safe, address(token), 0, data, Enum.Operation.Call);
        assertEq(token.allowance(address(safe), attacker), 0);
    }

    function test_multiSend_plainBatchWithinBudget_passes() public {
        bytes memory batch = abi.encodePacked(
            _packed(recipient, 3 ether, ""), _packed(address(token), 0, abi.encodeCall(token.transfer, (recipient, 10_000e6)))
        );
        _exec(safe, address(multiSend), 0, abi.encodeCall(multiSend.multiSend, (batch)), Enum.Operation.DelegateCall);
        assertEq(recipient.balance, 3 ether);
        assertEq(token.balanceOf(recipient), 10_000e6);
    }

    function test_multiSend_cannotSmuggleSensitiveCalls() public {
        bytes[] memory batches = new bytes[](3);
        // outflow above budget, split in two
        batches[0] = abi.encodePacked(_packed(attacker, 6 ether, ""), _packed(attacker, 6 ether, ""));
        // approval hidden behind a harmless call
        batches[1] = abi.encodePacked(
            _packed(recipient, 1 ether, ""), _packed(address(token), 0, abi.encodeCall(token.approve, (attacker, 1e30)))
        );
        // guard removal hidden behind a harmless call
        batches[2] = abi.encodePacked(
            _packed(recipient, 1 ether, ""), _packed(address(safe), 0, abi.encodeCall(safe.setGuard, (address(0))))
        );

        for (uint256 i = 0; i < batches.length; i++) {
            bytes memory data = abi.encodeCall(multiSend.multiSend, (batches[i]));
            _execRevert(
                _needsSchedule(address(multiSend), 0, data, Enum.Operation.DelegateCall),
                safe,
                address(multiSend),
                0,
                data,
                Enum.Operation.DelegateCall
            );
        }
        assertEq(attacker.balance, 0);
        assertEq(token.allowance(address(safe), attacker), 0);
        assertTrue(guard.isProtected(address(safe)));
    }

    function test_delegatecallToUnknownLibrary_requiresSchedule() public {
        MultiSendCallOnly other = new MultiSendCallOnly();
        bytes memory data = abi.encodeCall(other.multiSend, (_packed(recipient, 1 ether, "")));
        _execRevert(
            _needsSchedule(address(other), 0, data, Enum.Operation.DelegateCall),
            safe,
            address(other),
            0,
            data,
            Enum.Operation.DelegateCall
        );
    }

    // ---------------------------------------------------------------------------------------------
    // Layer 2: delay queue and veto
    // ---------------------------------------------------------------------------------------------

    function test_scheduledAction_runsAfterDelay_once() public {
        bytes32 hash = _schedule(recipient, 100 ether, "", Enum.Operation.Call);
        (, uint64 readyAt,,) = guard.schedules(address(safe), hash);
        assertEq(readyAt, block.timestamp + DELAY);

        vm.warp(block.timestamp + DELAY - 1);
        _execRevert(
            abi.encodeWithSelector(AegisSafeGuard.ActionNotReady.selector, hash, readyAt),
            safe,
            recipient,
            100 ether,
            "",
            Enum.Operation.Call
        );

        vm.warp(block.timestamp + 1);
        _exec(safe, recipient, 100 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 100 ether);
        // a scheduled outflow does not eat the routine budget
        assertEq(guard.available(address(safe), address(0)), ETH_LIMIT);

        // single use
        _execRevert(_needsSchedule(recipient, 100 ether, "", Enum.Operation.Call), safe, recipient, 100 ether, "", Enum.Operation.Call);
    }

    function test_safeStaysUsableWhileActionWaits() public {
        _schedule(recipient, 100 ether, "", Enum.Operation.Call);
        _exec(safe, recipient, 2 ether, "", Enum.Operation.Call);
        _exec(safe, recipient, 2 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 4 ether);
    }

    function test_scheduledAction_expires() public {
        bytes32 hash = _schedule(recipient, 100 ether, "", Enum.Operation.Call);
        vm.warp(block.timestamp + DELAY + guard.GRACE_PERIOD() + 1);
        _execRevert(
            abi.encodeWithSelector(AegisSafeGuard.ActionExpired.selector, hash), safe, recipient, 100 ether, "", Enum.Operation.Call
        );
    }

    function test_ownerVeto_cancelsScheduledDrain() public {
        // Thief holds 2 of 3 keys and schedules a drain; the third owner is enough to stop it.
        bytes32 hash = _schedule(attacker, 1000 ether, "", Enum.Operation.Call);

        vm.prank(attacker);
        vm.expectRevert(AegisSafeGuard.NotOwner.selector);
        guard.veto(address(safe), hash);

        vm.prank(owners[2]);
        guard.veto(address(safe), hash);

        vm.warp(block.timestamp + DELAY);
        _execRevert(_needsSchedule(attacker, 1000 ether, "", Enum.Operation.Call), safe, attacker, 1000 ether, "", Enum.Operation.Call);
        assertEq(attacker.balance, 0);
    }

    function test_guardRemoval_isPossibleThroughTheQueue() public {
        bytes memory data = abi.encodeCall(safe.setGuard, (address(0)));
        _schedule(address(safe), 0, data, Enum.Operation.Call);
        vm.warp(block.timestamp + DELAY);
        _exec(safe, address(safe), 0, data, Enum.Operation.Call);
        assertFalse(guard.isProtected(address(safe)));
    }

    // ---------------------------------------------------------------------------------------------
    // Layer 3: attester can shorten or tighten, nothing else
    // ---------------------------------------------------------------------------------------------

    function test_expedite_shortensDelay_butNotToZero() public {
        bytes32 hash = _schedule(recipient, 100 ether, "", Enum.Operation.Call);
        (uint64 scheduledAt,, uint32 epoch,) = guard.schedules(address(safe), hash);
        uint64 deadline = uint64(block.timestamp + 1 hours);
        bytes32 digest = guard.expediteDigest(address(safe), hash, scheduledAt, epoch, deadline);

        vm.expectRevert(AegisSafeGuard.InvalidAttestation.selector);
        guard.expedite(address(safe), hash, deadline, _attest(digest, 1));

        guard.expedite(address(safe), hash, deadline, _attest(digest, 2));
        (, uint64 readyAt,,) = guard.schedules(address(safe), hash);
        assertEq(readyAt, scheduledAt + EXPEDITED);

        _execRevert(
            abi.encodeWithSelector(AegisSafeGuard.ActionNotReady.selector, hash, readyAt),
            safe,
            recipient,
            100 ether,
            "",
            Enum.Operation.Call
        );
        vm.warp(block.timestamp + EXPEDITED);
        _exec(safe, recipient, 100 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 100 ether);
    }

    function test_attesterAlone_cannotMoveFunds() public {
        // A fully compromised attester set can sign anything; without a schedule from the owners it does nothing.
        bytes32 hash = guard.actionHash(address(safe), attacker, 1000 ether, "", AegisSafeGuard.Operation.Call);
        uint64 deadline = uint64(block.timestamp + 1 hours);
        bytes32 digest = guard.expediteDigest(address(safe), hash, uint64(block.timestamp), 1, deadline);

        vm.expectRevert(abi.encodeWithSelector(AegisSafeGuard.NotScheduled.selector, hash));
        guard.expedite(address(safe), hash, deadline, _attest(digest, 3));
    }

    function test_freeze_zeroesBudget_andIsBounded() public {
        uint64 deadline = uint64(block.timestamp + 1 hours);
        bytes memory proof = _attest(guard.freezeDigest(address(safe), 6 hours, 0, deadline), 2);

        vm.expectRevert(AegisSafeGuard.InvalidFreeze.selector);
        guard.freeze(address(safe), 25 hours, deadline, proof);

        guard.freeze(address(safe), 6 hours, deadline, proof);
        assertEq(guard.available(address(safe), address(0)), 0);
        _execRevert(_needsSchedule(recipient, 1 ether, "", Enum.Operation.Call), safe, recipient, 1 ether, "", Enum.Operation.Call);

        // Bounded harm: it ends on its own...
        vm.warp(block.timestamp + 6 hours);
        _exec(safe, recipient, 1 ether, "", Enum.Operation.Call);

        // ...cannot be re-armed immediately...
        uint64 deadline2 = uint64(block.timestamp + 1 hours);
        bytes memory proof2 = _attest(guard.freezeDigest(address(safe), 6 hours, 1, deadline2), 2);
        vm.expectRevert(
            abi.encodeWithSelector(AegisSafeGuard.FreezeCooldown.selector, uint64(block.timestamp) + guard.FREEZE_COOLDOWN())
        );
        guard.freeze(address(safe), 6 hours, deadline2, proof2);

        // ...and an old proof cannot be replayed.
        vm.warp(block.timestamp + guard.FREEZE_COOLDOWN());
        vm.expectRevert(AegisSafeGuard.AttestationExpired.selector);
        guard.freeze(address(safe), 6 hours, deadline, proof);
        vm.expectRevert(AegisSafeGuard.InvalidAttestation.selector);
        guard.freeze(address(safe), 6 hours, uint64(block.timestamp + 1 hours), proof);
    }

    function test_freeze_doesNotBlockMaturedSchedules() public {
        _schedule(recipient, 100 ether, "", Enum.Operation.Call);
        vm.warp(block.timestamp + DELAY);

        uint64 deadline = uint64(block.timestamp + 1 hours);
        guard.freeze(address(safe), 24 hours, deadline, _attest(guard.freezeDigest(address(safe), 24 hours, 0, deadline), 2));

        _exec(safe, recipient, 100 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 100 ether);
    }

    function test_thresholdAttester_rejectsBadProofs() public view {
        bytes32 digest = keccak256("digest");
        bytes memory s0 = _sig(attesterKeys[0], digest);
        bytes memory s1 = _sig(attesterKeys[1], digest);
        bytes memory outsider = _sig(0xBEEF, digest);

        assertTrue(attester.isValidAttestation(digest, abi.encodePacked(s0, s1)));
        assertFalse(attester.isValidAttestation(digest, s0)); // below threshold
        assertFalse(attester.isValidAttestation(digest, abi.encodePacked(s0, s0))); // duplicate
        assertFalse(attester.isValidAttestation(digest, abi.encodePacked(s1, s0))); // unsorted
        assertFalse(attester.isValidAttestation(digest, abi.encodePacked(s0, outsider))); // not a signer
        assertFalse(attester.isValidAttestation(keccak256("other"), abi.encodePacked(s0, s1))); // wrong digest
    }

    // ---------------------------------------------------------------------------------------------
    // Known gap: ERC-1271 permits never touch the guard
    // ---------------------------------------------------------------------------------------------

    function test_knownGap_erc1271PermitBypassesTheGuard() public {
        // With the default fallback handler, owner signatures validate off-chain messages. A thief holding the
        // keys signs a permit and never sends a Safe transaction, so no guard of any vendor gets called.
        bytes32 digest = token.permitDigest(address(safe), attacker, 1_000_000e6);
        bytes32 safeMessageHash = handler.getMessageHashForSafe(safe, abi.encode(digest));
        bytes memory sigs = _signOwners(safeMessageHash);

        vm.startPrank(attacker);
        token.permit1271(address(safe), attacker, 1_000_000e6, sigs);
        token.transferFrom(address(safe), attacker, 1_000_000e6);
        vm.stopPrank();

        assertEq(token.balanceOf(address(safe)), 0);
    }

    function test_noFallbackHandler_closesThePermitPath() public {
        Safe hardened = _deploySafe(address(0), 3);
        _installGuard(hardened, true);

        bytes32 digest = token.permitDigest(address(hardened), attacker, 1_000_000e6);
        bytes32 safeMessageHash = handler.getMessageHashForSafe(hardened, abi.encode(digest));
        bytes memory sigs = _signOwners(safeMessageHash);

        vm.prank(attacker);
        vm.expectRevert();
        token.permit1271(address(hardened), attacker, 1_000_000e6, sigs);

        // and re-adding a handler is a fingerprint change
        bytes memory data = abi.encodeCall(hardened.setFallbackHandler, (address(handler)));
        _execRevert(
            abi.encodeWithSelector(
                AegisSafeGuard.ActionRequiresSchedule.selector,
                guard.actionHash(address(hardened), address(hardened), 0, data, AegisSafeGuard.Operation.Call)
            ),
            hardened,
            address(hardened),
            0,
            data,
            Enum.Operation.Call
        );
    }

    function test_forbidFallbackHandler_rejectsSafeThatHasOne() public {
        (AegisSafeGuard.PolicyParams memory p, address[] memory assets, uint128[] memory limits) =
            _policy(true, ETH_LIMIT, TOKEN_LIMIT);
        vm.prank(address(safe));
        vm.expectRevert(AegisSafeGuard.FallbackHandlerPresent.selector);
        guard.configure(p, assets, limits);
    }

    // ---------------------------------------------------------------------------------------------
    // Misc
    // ---------------------------------------------------------------------------------------------

    function test_unconfiguredSafe_isPassedThrough_notBricked() public {
        Safe bare = _deploySafe(address(handler), 4);
        _exec(bare, address(bare), 0, abi.encodeCall(bare.setGuard, (address(guard))), Enum.Operation.Call);
        assertFalse(guard.isProtected(address(bare)));
        _exec(bare, recipient, 500 ether, "", Enum.Operation.Call);
        assertEq(recipient.balance, 500 ether);
    }

    function test_invalidPolicy_reverts() public {
        (AegisSafeGuard.PolicyParams memory p, address[] memory assets, uint128[] memory limits) =
            _policy(false, ETH_LIMIT, TOKEN_LIMIT);
        p.delay = 10 minutes;
        vm.expectRevert(AegisSafeGuard.InvalidPolicy.selector);
        guard.configure(p, assets, limits);

        p.delay = DELAY;
        assets[1] = address(0); // duplicate asset
        vm.expectRevert(AegisSafeGuard.InvalidPolicy.selector);
        guard.configure(p, assets, limits);
    }

    // ---------------------------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------------------------

    function _deploySafe(address fallbackHandler, uint256 salt) internal returns (Safe s) {
        bytes memory init =
            abi.encodeCall(Safe.setup, (owners, 2, address(0), "", fallbackHandler, address(0), 0, payable(address(0))));
        s = Safe(payable(address(factory.createProxyWithNonce(address(singleton), init, salt))));
        vm.deal(address(s), 1000 ether);
        token.mint(address(s), 1_000_000e6);
    }

    function _installGuard(Safe s, bool forbidHandler) internal {
        _exec(s, address(guard), 0, _configureCall(forbidHandler, ETH_LIMIT, TOKEN_LIMIT), Enum.Operation.Call);
        _exec(s, address(s), 0, abi.encodeCall(s.setGuard, (address(guard))), Enum.Operation.Call);
    }

    function _policy(bool forbidHandler, uint128 ethLimit, uint128 tokenLimit)
        internal
        view
        returns (AegisSafeGuard.PolicyParams memory p, address[] memory assets, uint128[] memory limits)
    {
        p = AegisSafeGuard.PolicyParams({
            attester: address(attester),
            multiSend: address(multiSend),
            delay: DELAY,
            expeditedDelay: EXPEDITED,
            window: WINDOW,
            vetoQuorum: 1,
            forbidFallbackHandler: forbidHandler
        });
        assets = new address[](2);
        assets[0] = address(0);
        assets[1] = address(token);
        limits = new uint128[](2);
        limits[0] = ethLimit;
        limits[1] = tokenLimit;
    }

    function _configureCall(bool forbidHandler, uint128 ethLimit, uint128 tokenLimit) internal view returns (bytes memory) {
        (AegisSafeGuard.PolicyParams memory p, address[] memory assets, uint128[] memory limits) =
            _policy(forbidHandler, ethLimit, tokenLimit);
        return abi.encodeCall(guard.configure, (p, assets, limits));
    }

    function _schedule(address to, uint256 value, bytes memory data, Enum.Operation op) internal returns (bytes32) {
        AegisSafeGuard.Operation gop = AegisSafeGuard.Operation(uint8(op));
        _exec(safe, address(guard), 0, abi.encodeCall(guard.schedule, (to, value, data, gop)), Enum.Operation.Call);
        return guard.actionHash(address(safe), to, value, data, gop);
    }

    function _needsSchedule(address to, uint256 value, bytes memory data, Enum.Operation op)
        internal
        view
        returns (bytes memory)
    {
        return abi.encodeWithSelector(
            AegisSafeGuard.ActionRequiresSchedule.selector,
            guard.actionHash(address(safe), to, value, data, AegisSafeGuard.Operation(uint8(op)))
        );
    }

    // Safe's 10-argument calls overflow the legacy stack unless the transaction travels as one memory struct.
    struct Tx {
        address to;
        uint256 value;
        bytes data;
        Enum.Operation op;
    }

    function _exec(Safe s, address to, uint256 value, bytes memory data, Enum.Operation op) internal {
        _send(s, Tx(to, value, data, op), "", false);
    }

    function _execRevert(bytes memory err, Safe s, address to, uint256 value, bytes memory data, Enum.Operation op)
        internal
    {
        _send(s, Tx(to, value, data, op), err, true);
    }

    function _send(Safe s, Tx memory t, bytes memory err, bool expectRevert) internal {
        bytes memory sigs = _signOwners(_txHash(s, t));
        if (expectRevert) vm.expectRevert(err);
        bool ok = s.execTransaction(t.to, t.value, t.data, t.op, 0, 0, 0, address(0), payable(address(0)), sigs);
        if (!expectRevert) assertTrue(ok);
    }

    function _txHash(Safe s, Tx memory t) internal view returns (bytes32) {
        uint256 nonce = s.nonce();
        return s.getTransactionHash(t.to, t.value, t.data, t.op, 0, 0, 0, address(0), payable(address(0)), nonce);
    }

    /// @dev Two lowest-address owners, in the ascending order Safe requires.
    function _signOwners(bytes32 hash) internal view returns (bytes memory) {
        return abi.encodePacked(_sig(ownerKeys[0], hash), _sig(ownerKeys[1], hash));
    }

    function _attest(bytes32 digest, uint256 count) internal view returns (bytes memory proof) {
        for (uint256 i = 0; i < count; i++) {
            proof = abi.encodePacked(proof, _sig(attesterKeys[i], digest));
        }
    }

    function _sig(uint256 key, bytes32 hash) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, hash);
        return abi.encodePacked(r, s, v);
    }

    function _packed(address to, uint256 value, bytes memory data) internal pure returns (bytes memory) {
        return abi.encodePacked(uint8(0), to, value, data.length, data);
    }

    function _sortedKeys(string memory label, uint256 n) internal returns (address[] memory addrs, uint256[] memory keys) {
        addrs = new address[](n);
        keys = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            (addrs[i], keys[i]) = makeAddrAndKey(string.concat(label, vm.toString(i)));
        }
        for (uint256 i = 0; i < n; i++) {
            for (uint256 j = i + 1; j < n; j++) {
                if (addrs[j] < addrs[i]) {
                    (addrs[i], addrs[j]) = (addrs[j], addrs[i]);
                    (keys[i], keys[j]) = (keys[j], keys[i]);
                }
            }
        }
    }
}

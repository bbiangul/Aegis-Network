// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { IAttester } from "./IAttester.sol";

interface ISafeView {
    function getOwners() external view returns (address[] memory);
    function getThreshold() external view returns (uint256);
    function isOwner(address owner) external view returns (bool);
    function getModulesPaginated(address start, uint256 pageSize) external view returns (address[] memory, address);
    function getStorageAt(uint256 offset, uint256 length) external view returns (bytes memory);
    /// @dev Answered by the SafeProxy itself, not by the singleton, so a swapped singleton cannot lie about it.
    function masterCopy() external view returns (address);
}

interface IBalanceOf {
    function balanceOf(address account) external view returns (uint256);
}

/// @title AegisSafeGuard
/// @notice Transaction guard for Safe accounts that checks what a transaction DID, not what its calldata says.
///
///         Layer 1 (deterministic): after every execution the guard compares the Safe before and after.
///           - configuration (singleton, owners, threshold, modules, guard, fallback handler, this guard's
///             own policy) must be unchanged
///           - net outflow of each tracked asset must fit a decaying per-window budget
///           - delegatecalls (other than a parsed MultiSend batch), token approvals and gas refunds are
///             never "routine"
///         Layer 2 (delay): anything outside layer 1 reverts unless the Safe scheduled that exact action
///           `delay` seconds earlier. Owners can veto while it waits.
///         Layer 3 (attester, optional): can shorten a pending delay or freeze the outflow budget for a
///           bounded time. It can never approve, block permanently, or move funds. If it disappears the
///           Safe still works, just slower.
///
/// @dev One deployment serves any number of Safes; all state is keyed by the calling Safe.
///      Prototype: per-transaction context lives in regular storage (transient storage would be cheaper).
contract AegisSafeGuard {
    enum Operation {
        Call,
        DelegateCall
    }

    struct PolicyParams {
        address attester; // optional, address(0) disables layer 3
        address multiSend; // optional MultiSendCallOnly whose batches the guard parses
        uint32 delay; // wait for anything outside the envelope
        uint32 expeditedDelay; // wait once the attester vouches for a scheduled action
        uint32 window; // budget refill period
        uint8 vetoQuorum; // owners needed to cancel a scheduled action
        bool forbidFallbackHandler; // require no fallback handler at configure time (closes ERC-1271 permit path)
    }

    struct Policy {
        address attester;
        address multiSend;
        uint32 delay;
        uint32 expeditedDelay;
        uint32 window;
        uint8 vetoQuorum;
        bool initialized;
    }

    struct Bucket {
        uint128 limit;
        uint128 spent;
        uint64 updatedAt;
    }

    struct Schedule {
        uint64 scheduledAt;
        uint64 readyAt;
        uint32 epoch;
        uint8 vetoes;
    }

    struct Context {
        bool active;
        bool flagged;
        bytes32 actionHash;
        bytes32 fingerprint;
    }

    uint256 public constant MAX_ASSETS = 16;
    uint32 public constant MIN_DELAY = 1 hours;
    uint32 public constant MIN_EXPEDITED_DELAY = 5 minutes;
    uint32 public constant GRACE_PERIOD = 7 days;
    uint32 public constant MAX_FREEZE = 24 hours;
    uint32 public constant FREEZE_COOLDOWN = 24 hours;

    // keccak256("guard_manager.guard.address")
    uint256 internal constant GUARD_SLOT = 0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8;
    // keccak256("fallback_manager.handler.address")
    uint256 internal constant FALLBACK_HANDLER_SLOT = 0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5;
    address internal constant SENTINEL_MODULES = address(0x1);

    bytes4 internal constant MULTISEND_SELECTOR = 0x8d80ff0a; // multiSend(bytes)
    bytes4 internal constant APPROVE_SELECTOR = 0x095ea7b3; // approve(address,uint256)
    bytes4 internal constant INCREASE_ALLOWANCE_SELECTOR = 0x39509351; // increaseAllowance(address,uint256)
    bytes4 internal constant SET_APPROVAL_FOR_ALL_SELECTOR = 0xa22cb465; // setApprovalForAll(address,bool)
    bytes4 internal constant PERMIT2_APPROVE_SELECTOR = 0x87517c45; // approve(address,address,uint160,uint48)

    bytes32 internal constant EXPEDITE_TYPEHASH = keccak256("AegisSafeGuard.Expedite");
    bytes32 internal constant FREEZE_TYPEHASH = keccak256("AegisSafeGuard.Freeze");

    mapping(address safe => Policy) public policy;
    /// @notice Bumped on every policy change so the guard's own config is part of the Safe's fingerprint.
    mapping(address safe => uint256) public configNonce;
    mapping(address safe => mapping(address asset => Bucket)) public buckets;
    mapping(address safe => mapping(bytes32 actionHash => Schedule)) public schedules;
    mapping(address safe => mapping(uint32 epoch => mapping(address owner => bool))) public hasVetoed;
    mapping(address safe => uint64) public frozenUntil;
    mapping(address safe => uint256) public freezeNonce;

    mapping(address safe => address[]) internal _assets;
    mapping(address safe => uint32) internal _scheduleEpoch;
    mapping(address safe => Context) internal _ctx;
    mapping(address safe => uint256[]) internal _preBalances;

    error InvalidPolicy();
    error NotConfigured();
    error FallbackHandlerPresent();
    error NestedExecution();
    error RefundNotAllowed();
    error ActionRequiresSchedule(bytes32 actionHash);
    error ActionNotReady(bytes32 actionHash, uint64 readyAt);
    error ActionExpired(bytes32 actionHash);
    error AlreadyScheduled(bytes32 actionHash);
    error NotScheduled(bytes32 actionHash);
    error NotOwner();
    error AlreadyVetoed();
    error NoAttester();
    error InvalidAttestation();
    error AttestationExpired();
    error InvalidFreeze();
    error FreezeCooldown(uint64 availableAt);

    event Configured(address indexed safe, uint256 configNonce);
    event ActionScheduled(
        address indexed safe,
        bytes32 indexed actionHash,
        address to,
        uint256 value,
        bytes data,
        Operation operation,
        uint64 readyAt
    );
    event ActionCancelled(address indexed safe, bytes32 indexed actionHash);
    event ActionVetoed(address indexed safe, bytes32 indexed actionHash, address indexed owner, bool cancelled);
    event ActionExpedited(address indexed safe, bytes32 indexed actionHash, uint64 readyAt);
    event ActionExecuted(address indexed safe, bytes32 indexed actionHash);
    event Frozen(address indexed safe, uint64 until);

    // ---------------------------------------------------------------------------------------------
    // Configuration (called by the Safe itself)
    // ---------------------------------------------------------------------------------------------

    /// @notice Set or replace the calling Safe's policy. Once the guard is installed, this call changes the
    ///         Safe's fingerprint and therefore must itself be scheduled and wait out the delay.
    /// @param assets Tracked assets; address(0) is the native token.
    /// @param limits Net outflow allowed per `window` for each asset, refilling linearly.
    function configure(PolicyParams calldata p, address[] calldata assets, uint128[] calldata limits) external {
        address safe = msg.sender;
        if (
            p.delay < MIN_DELAY || p.expeditedDelay < MIN_EXPEDITED_DELAY || p.expeditedDelay > p.delay
                || p.window == 0 || p.vetoQuorum == 0 || assets.length != limits.length || assets.length > MAX_ASSETS
        ) revert InvalidPolicy();

        if (p.forbidFallbackHandler && _readAddressSlot(safe, FALLBACK_HANDLER_SLOT) != address(0)) {
            revert FallbackHandlerPresent();
        }

        address[] storage current = _assets[safe];
        for (uint256 i = 0; i < current.length; i++) {
            delete buckets[safe][current[i]];
        }
        delete _assets[safe];

        for (uint256 i = 0; i < assets.length; i++) {
            if (buckets[safe][assets[i]].updatedAt != 0) revert InvalidPolicy(); // duplicate
            buckets[safe][assets[i]] = Bucket({ limit: limits[i], spent: 0, updatedAt: uint64(block.timestamp) });
            _assets[safe].push(assets[i]);
        }

        policy[safe] = Policy({
            attester: p.attester,
            multiSend: p.multiSend,
            delay: p.delay,
            expeditedDelay: p.expeditedDelay,
            window: p.window,
            vetoQuorum: p.vetoQuorum,
            initialized: true
        });

        emit Configured(safe, ++configNonce[safe]);
    }

    // ---------------------------------------------------------------------------------------------
    // Delay queue
    // ---------------------------------------------------------------------------------------------

    /// @notice Announce an out-of-envelope action. The hash is nonce-independent, so the Safe keeps working
    ///         normally while the action waits.
    function schedule(address to, uint256 value, bytes calldata data, Operation operation)
        external
        returns (bytes32 hash)
    {
        address safe = msg.sender;
        Policy storage p = policy[safe];
        if (!p.initialized) revert NotConfigured();

        hash = actionHash(safe, to, value, data, operation);
        Schedule storage s = schedules[safe][hash];
        if (s.scheduledAt != 0 && block.timestamp <= uint256(s.readyAt) + GRACE_PERIOD) revert AlreadyScheduled(hash);

        uint64 readyAt = uint64(block.timestamp) + p.delay;
        schedules[safe][hash] =
            Schedule({ scheduledAt: uint64(block.timestamp), readyAt: readyAt, epoch: ++_scheduleEpoch[safe], vetoes: 0 });

        emit ActionScheduled(safe, hash, to, value, data, operation, readyAt);
    }

    function cancel(bytes32 hash) external {
        if (schedules[msg.sender][hash].scheduledAt == 0) revert NotScheduled(hash);
        delete schedules[msg.sender][hash];
        emit ActionCancelled(msg.sender, hash);
    }

    /// @notice Any Safe owner can vote to cancel a pending action; `vetoQuorum` votes cancel it.
    function veto(address safe, bytes32 hash) external {
        if (!ISafeView(safe).isOwner(msg.sender)) revert NotOwner();
        Schedule storage s = schedules[safe][hash];
        if (s.scheduledAt == 0) revert NotScheduled(hash);
        if (hasVetoed[safe][s.epoch][msg.sender]) revert AlreadyVetoed();

        hasVetoed[safe][s.epoch][msg.sender] = true;
        bool cancelled = ++s.vetoes >= policy[safe].vetoQuorum;
        if (cancelled) delete schedules[safe][hash];

        emit ActionVetoed(safe, hash, msg.sender, cancelled);
    }

    // ---------------------------------------------------------------------------------------------
    // Attester powers: shorten a delay, or tighten the budget. Nothing else.
    // ---------------------------------------------------------------------------------------------

    /// @notice With a valid attestation, a scheduled action becomes executable `expeditedDelay` after it was
    ///         scheduled instead of `delay`. Anyone may relay the proof.
    function expedite(address safe, bytes32 hash, uint64 deadline, bytes calldata proof) external {
        Policy storage p = policy[safe];
        Schedule storage s = schedules[safe][hash];
        if (s.scheduledAt == 0) revert NotScheduled(hash);

        bytes32 digest = expediteDigest(safe, hash, s.scheduledAt, s.epoch, deadline);
        _requireAttestation(p.attester, digest, deadline, proof);

        uint64 readyAt = s.scheduledAt + p.expeditedDelay;
        if (readyAt < s.readyAt) s.readyAt = readyAt;

        emit ActionExpedited(safe, hash, s.readyAt);
    }

    /// @notice With a valid attestation, the Safe's outflow budget drops to zero for `duration`. Scheduled
    ///         actions are unaffected. Bounded by MAX_FREEZE and a cooldown so it cannot be made permanent.
    function freeze(address safe, uint32 duration, uint64 deadline, bytes calldata proof) external {
        if (duration == 0 || duration > MAX_FREEZE) revert InvalidFreeze();
        uint64 until = frozenUntil[safe];
        if (until != 0 && block.timestamp < uint256(until) + FREEZE_COOLDOWN) {
            revert FreezeCooldown(until + FREEZE_COOLDOWN);
        }

        bytes32 digest = freezeDigest(safe, duration, freezeNonce[safe]++, deadline);
        _requireAttestation(policy[safe].attester, digest, deadline, proof);

        until = uint64(block.timestamp) + duration;
        frozenUntil[safe] = until;
        emit Frozen(safe, until);
    }

    // ---------------------------------------------------------------------------------------------
    // Safe guard hooks
    // ---------------------------------------------------------------------------------------------

    function checkTransaction(
        address to,
        uint256 value,
        bytes memory data,
        Operation operation,
        uint256,
        uint256,
        uint256 gasPrice,
        address,
        address payable,
        bytes memory,
        address
    ) external {
        // No locals here: Safe's 11-argument hook leaves no stack room on the legacy pipeline.
        // An unconfigured Safe is passed through rather than bricked; see isProtected().
        if (!policy[msg.sender].initialized) return;
        // A nested execTransaction would overwrite the outer snapshot and hide what happened before it.
        if (_ctx[msg.sender].active) revert NestedExecution();
        // Refunds pay an arbitrary receiver in an arbitrary token, outside the action hash.
        if (gasPrice != 0) revert RefundNotAllowed();

        _ctx[msg.sender].actionHash = actionHash(msg.sender, to, value, data, operation);
        _ctx[msg.sender].flagged = _isFlagged(msg.sender, to, data, operation);
        _snapshot(msg.sender);
    }

    function _isFlagged(address safe, address to, bytes memory data, Operation operation)
        internal
        view
        returns (bool)
    {
        if (operation == Operation.DelegateCall) {
            return (to != address(0) && to == policy[safe].multiSend) ? _batchIsSensitive(data) : true;
        }
        return data.length >= 4 && _isSensitiveSelector(bytes4(data));
    }

    function _snapshot(address safe) internal {
        Context storage c = _ctx[safe];
        c.active = true;
        c.fingerprint = configFingerprint(safe);

        address[] storage assets = _assets[safe];
        delete _preBalances[safe];
        uint256[] storage pre = _preBalances[safe];
        for (uint256 i = 0; i < assets.length; i++) {
            pre.push(_balance(safe, assets[i]));
        }
    }

    function checkAfterExecution(bytes32, bool) external {
        address safe = msg.sender;
        Context storage c = _ctx[safe];
        if (!c.active) return;

        bool violated = c.flagged;

        // A swapped singleton may revert or lie on Safe getters; masterCopy() is answered by the proxy.
        try this.configFingerprint(safe) returns (bytes32 fp) {
            if (fp != c.fingerprint) violated = true;
        } catch {
            violated = true;
        }

        address[] storage assets = _assets[safe];
        uint256[] storage pre = _preBalances[safe];
        uint256 n = assets.length;
        uint256[] memory outflows = new uint256[](n);

        if (n != pre.length) {
            violated = true; // policy was replaced mid-transaction
        } else {
            bool frozen = block.timestamp < frozenUntil[safe];
            uint32 window = policy[safe].window;
            for (uint256 i = 0; i < n; i++) {
                uint256 post = _balance(safe, assets[i]);
                if (post >= pre[i]) continue;
                outflows[i] = pre[i] - post;
                if (frozen || outflows[i] > _available(buckets[safe][assets[i]], window)) violated = true;
            }
        }

        bytes32 hash = c.actionHash;
        delete _ctx[safe];

        if (violated) {
            _consumeSchedule(safe, hash);
        } else {
            uint32 window = policy[safe].window;
            for (uint256 i = 0; i < n; i++) {
                if (outflows[i] != 0) _spend(buckets[safe][assets[i]], window, outflows[i]);
            }
        }
    }

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == 0xe6d7a83a // Safe Guard
            || interfaceId == 0x01ffc9a7; // ERC-165
    }

    // ---------------------------------------------------------------------------------------------
    // Views
    // ---------------------------------------------------------------------------------------------

    function actionHash(address safe, address to, uint256 value, bytes memory data, Operation operation)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(safe, to, value, keccak256(data), operation));
    }

    /// @notice Everything about the Safe that decides who controls it and how it is guarded.
    function configFingerprint(address safe) public view returns (bytes32) {
        ISafeView s = ISafeView(safe);
        (address[] memory modules, address next) = s.getModulesPaginated(SENTINEL_MODULES, 16);
        return keccak256(
            abi.encode(
                s.masterCopy(),
                s.getOwners(),
                s.getThreshold(),
                modules,
                next,
                s.getStorageAt(GUARD_SLOT, 1),
                s.getStorageAt(FALLBACK_HANDLER_SLOT, 1),
                configNonce[safe]
            )
        );
    }

    function expediteDigest(address safe, bytes32 hash, uint64 scheduledAt, uint32 epoch, uint64 deadline)
        public
        view
        returns (bytes32)
    {
        return
            keccak256(abi.encode(EXPEDITE_TYPEHASH, block.chainid, address(this), safe, hash, scheduledAt, epoch, deadline));
    }

    function freezeDigest(address safe, uint32 duration, uint256 nonce, uint64 deadline) public view returns (bytes32) {
        return keccak256(abi.encode(FREEZE_TYPEHASH, block.chainid, address(this), safe, duration, nonce, deadline));
    }

    /// @notice Outflow of `asset` the Safe can make right now without scheduling.
    function available(address safe, address asset) external view returns (uint256) {
        if (block.timestamp < frozenUntil[safe]) return 0;
        return _available(buckets[safe][asset], policy[safe].window);
    }

    function trackedAssets(address safe) external view returns (address[] memory) {
        return _assets[safe];
    }

    /// @notice True only when the Safe has a policy AND this contract is installed as its guard.
    function isProtected(address safe) external view returns (bool) {
        return policy[safe].initialized && _readAddressSlot(safe, GUARD_SLOT) == address(this);
    }

    // ---------------------------------------------------------------------------------------------
    // Internals
    // ---------------------------------------------------------------------------------------------

    function _consumeSchedule(address safe, bytes32 hash) internal {
        Schedule storage s = schedules[safe][hash];
        if (s.scheduledAt == 0) revert ActionRequiresSchedule(hash);
        if (block.timestamp < s.readyAt) revert ActionNotReady(hash, s.readyAt);
        if (block.timestamp > uint256(s.readyAt) + GRACE_PERIOD) revert ActionExpired(hash);
        delete schedules[safe][hash];
        emit ActionExecuted(safe, hash);
    }

    function _requireAttestation(address attester, bytes32 digest, uint64 deadline, bytes calldata proof)
        internal
        view
    {
        if (attester == address(0)) revert NoAttester();
        if (block.timestamp > deadline) revert AttestationExpired();
        if (!IAttester(attester).isValidAttestation(digest, proof)) revert InvalidAttestation();
    }

    function _decayedSpent(Bucket storage b, uint32 window) internal view returns (uint256) {
        uint256 elapsed = block.timestamp - b.updatedAt;
        if (elapsed >= window) return 0;
        uint256 refill = (uint256(b.limit) * elapsed) / window;
        return b.spent > refill ? b.spent - refill : 0;
    }

    function _available(Bucket storage b, uint32 window) internal view returns (uint256) {
        if (b.updatedAt == 0) return 0;
        uint256 spent = _decayedSpent(b, window);
        return b.limit > spent ? b.limit - spent : 0;
    }

    function _spend(Bucket storage b, uint32 window, uint256 amount) internal {
        // amount <= available <= limit, so the sum fits in uint128
        b.spent = uint128(_decayedSpent(b, window) + amount);
        b.updatedAt = uint64(block.timestamp);
    }

    function _balance(address safe, address asset) internal view returns (uint256) {
        return asset == address(0) ? safe.balance : IBalanceOf(asset).balanceOf(safe);
    }

    function _readAddressSlot(address safe, uint256 slot) internal view returns (address) {
        return address(uint160(uint256(bytes32(ISafeView(safe).getStorageAt(slot, 1)))));
    }

    function _isSensitiveSelector(bytes4 selector) internal pure returns (bool) {
        return selector == APPROVE_SELECTOR || selector == INCREASE_ALLOWANCE_SELECTOR
            || selector == SET_APPROVAL_FOR_ALL_SELECTOR || selector == PERMIT2_APPROVE_SELECTOR;
    }

    /// @dev Walks a MultiSend payload (op:1 | to:20 | value:32 | len:32 | data). Anything that is not a plain,
    ///      well-formed batch of non-approval calls is treated as sensitive.
    function _batchIsSensitive(bytes memory data) internal pure returns (bool) {
        if (data.length < 68 || bytes4(data) != MULTISEND_SELECTOR) return true;

        uint256 offset;
        uint256 len;
        assembly {
            offset := mload(add(data, 36))
            len := mload(add(data, 68))
        }
        if (offset != 32 || len > data.length - 68) return true;

        uint256 i = 0;
        while (i < len) {
            if (len - i < 85) return true;
            uint256 op;
            uint256 dataLen;
            uint256 word;
            assembly {
                let p := add(add(data, 100), i)
                op := shr(248, mload(p))
                dataLen := mload(add(p, 53))
                word := mload(add(p, 85))
            }
            if (op != 0) return true;
            if (dataLen > len - i - 85) return true;
            if (dataLen >= 4 && _isSensitiveSelector(bytes4(bytes32(word)))) return true;
            i += 85 + dataLen;
        }
        return false;
    }
}

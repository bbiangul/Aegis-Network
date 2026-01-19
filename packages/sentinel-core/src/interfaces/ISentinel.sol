// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ISentinel {
    function pause() external;
    function unpause() external;
    function paused() external view returns (bool);
}

interface ISentinelPausable {
    function sentinelPause() external;
    function sentinelUnpause() external;
    function isSentinelPaused() external view returns (bool);
    function sentinelRouter() external view returns (address);
}

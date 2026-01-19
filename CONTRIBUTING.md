# Contributing to Aegis Network

Thank you for your interest in contributing to Aegis Network. This document provides guidelines and information for contributors.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Testing Guidelines](#testing-guidelines)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)

## Getting Started

Aegis Network is a monorepo containing three main packages:

| Package | Language | Description |
|---------|----------|-------------|
| `sentinel-brain` | Python | AI/ML engine for exploit detection |
| `sentinel-core` | Solidity | Smart contracts (token, staking, router) |
| `sentinel-node` | Go | Node software for mempool monitoring |

## Development Setup

### Prerequisites

- **Python 3.9+** for sentinel-brain
- **Foundry** for sentinel-core
- **Go 1.21+** for sentinel-node
- **Anvil** (part of Foundry) for local testing

### Clone and Install

```bash
git clone https://github.com/your-org/ai_crypto_guard.git
cd ai_crypto_guard

# Install sentinel-brain
cd packages/sentinel-brain
pip install -e ".[dev]"

# Install sentinel-core dependencies
cd ../sentinel-core
forge install

# Install sentinel-node dependencies
cd ../sentinel-node
go mod download
```

### Running Tests

```bash
# Python tests
cd packages/sentinel-brain
pytest tests/ -v

# Solidity tests
cd packages/sentinel-core
forge test -vvv

# Go tests
cd packages/sentinel-node
go test -v -race ./...
```

## Project Structure

```
ai_crypto_guard/
├── packages/
│   ├── sentinel-brain/           # Python AI/ML
│   │   ├── src/sentinel_brain/
│   │   │   ├── data/             # Data collection & exploit registry
│   │   │   ├── features/         # Feature extractors
│   │   │   ├── models/           # ML models (Isolation Forest)
│   │   │   └── inference/        # Production inference engine
│   │   └── tests/
│   │
│   ├── sentinel-core/            # Solidity contracts
│   │   ├── src/
│   │   │   ├── interfaces/       # Protocol integration interfaces
│   │   │   ├── SentinelToken.sol
│   │   │   ├── SentinelRegistry.sol
│   │   │   ├── SentinelShield.sol
│   │   │   └── SentinelRouter.sol
│   │   └── test/
│   │
│   └── sentinel-node/            # Go node software
│       ├── cmd/sentinel/         # Entry point
│       ├── internal/             # Internal packages
│       │   ├── mempool/          # Mempool listener
│       │   ├── consensus/        # BLS + gossip
│       │   └── inference/        # Python bridge
│       └── pkg/types/            # Shared types
│
├── docs/
└── data/                         # Training data (gitignored)
```

## Development Workflow

### Branching Strategy

- `main` - Production-ready code
- `develop` - Integration branch for features
- `feature/*` - New features
- `fix/*` - Bug fixes
- `docs/*` - Documentation updates

### Creating a Feature Branch

```bash
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name
```

### Making Changes

1. Write tests first (TDD approach)
2. Implement the feature
3. Ensure all tests pass
4. Update documentation if needed
5. Submit a pull request

## Testing Guidelines

### sentinel-brain (Python)

```python
# Test file naming: test_*.py
# Use pytest fixtures for setup/teardown
# Aim for >80% coverage on new code

def test_feature_extractor_returns_expected_shape():
    extractor = FlashLoanExtractor()
    features = extractor.extract(sample_trace)
    assert len(features) == 10
```

### sentinel-core (Solidity)

```solidity
// Test file naming: *.t.sol
// Use Foundry's forge-std for assertions
// Test all edge cases and failure modes

function test_RegisterNode_WithMinimumStake() public {
    token.approve(address(registry), MIN_STAKE);
    registry.registerNode(MIN_STAKE, blsKey);
    assertTrue(registry.isActiveNode(address(this)));
}
```

### sentinel-node (Go)

```go
// Test file naming: *_test.go
// Use table-driven tests
// Test concurrent access with -race flag

func TestBridgeAnalyze(t *testing.T) {
    tests := []struct {
        name     string
        tx       *types.PendingTransaction
        expected bool
    }{
        {"simple transfer", simpleTx, false},
        {"flash loan", flashLoanTx, true},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            result, _ := bridge.Analyze(ctx, tt.tx)
            if result.IsSuspicious != tt.expected {
                t.Errorf("expected %v, got %v", tt.expected, result.IsSuspicious)
            }
        })
    }
}
```

## Code Style

### Python

- Follow PEP 8
- Use type hints
- Maximum line length: 100 characters
- Use `ruff` for linting

```bash
pip install ruff
ruff check src/ tests/
ruff format src/ tests/
```

### Solidity

- Follow Solidity style guide
- Use NatSpec comments for public functions
- Maximum line length: 120 characters
- Use `forge fmt` for formatting

```bash
forge fmt
```

### Go

- Follow Go conventions
- Use `gofmt` and `go vet`
- Use meaningful variable names
- Handle all errors

```bash
go fmt ./...
go vet ./...
```

## Pull Request Process

### Before Submitting

1. Ensure all tests pass locally
2. Update documentation for any API changes
3. Add tests for new functionality
4. Run linters and formatters
5. Rebase on latest `develop`

### PR Template

When creating a PR, include:

- **Summary**: Brief description of changes
- **Motivation**: Why is this change needed?
- **Testing**: How was this tested?
- **Breaking Changes**: Any breaking changes?
- **Checklist**:
  - [ ] Tests pass
  - [ ] Documentation updated
  - [ ] No new warnings

### Review Process

1. At least one maintainer approval required
2. All CI checks must pass
3. Address all review comments
4. Squash commits before merge (optional)

## Reporting Issues

### Bug Reports

Include:
- Clear description of the bug
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, versions)
- Relevant logs or error messages

### Feature Requests

Include:
- Clear description of the feature
- Use case / motivation
- Proposed implementation (optional)
- Alternatives considered

### Security Vulnerabilities

**Do not open public issues for security vulnerabilities.**

See [SECURITY.md](./SECURITY.md) for responsible disclosure process.

## Additional Resources

- [README.md](./README.md) - Project overview
- [sentinel-brain/README.md](./packages/sentinel-brain/README.md) - AI/ML documentation
- [sentinel-core/README.md](./packages/sentinel-core/README.md) - Smart contract documentation
- [sentinel-node/README.md](./packages/sentinel-node/README.md) - Node software documentation

## Questions?

- Open a [Discussion](https://github.com/your-org/ai_crypto_guard/discussions)
- Join our Discord (coming soon)

Thank you for contributing to DeFi security.

# Security Policy

Aegis Network is security infrastructure for DeFi. We take security seriously and appreciate responsible disclosure of vulnerabilities.

## Supported Versions

| Package | Version | Supported |
|---------|---------|-----------|
| sentinel-brain | 0.1.x | Yes |
| sentinel-core | 0.1.x | Yes |
| sentinel-node | 0.1.x | Yes |

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

### Responsible Disclosure Process

1. **Email**: Send details to `security@aegis-network.io` (or create a private security advisory on GitHub)

2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (optional)

3. **Response Timeline**:
   - Initial response: 24-48 hours
   - Status update: within 7 days
   - Fix timeline: depends on severity

### Severity Classification

| Severity | Description | Example |
|----------|-------------|---------|
| **Critical** | Immediate fund loss risk | Smart contract drain, signature bypass |
| **High** | Significant security impact | False positive manipulation, consensus attack |
| **Medium** | Limited security impact | DoS vector, information disclosure |
| **Low** | Minimal security impact | Edge case bugs, minor issues |

## Scope

### In Scope

- Smart contracts (`sentinel-core/src/`)
- Node software (`sentinel-node/`)
- AI/ML inference engine (`sentinel-brain/`)
- Cryptographic implementations (BLS signatures)
- P2P network protocol

### Out of Scope

- Third-party dependencies (report upstream)
- Issues in test files only
- Documentation typos
- Social engineering attacks

## Bug Bounty

We plan to launch a bug bounty program. Details coming soon.

### Preliminary Rewards (Subject to Change)

| Severity | Reward Range |
|----------|--------------|
| Critical | $10,000 - $50,000 |
| High | $5,000 - $10,000 |
| Medium | $1,000 - $5,000 |
| Low | $100 - $1,000 |

## Security Best Practices

### For Node Operators

- Store BLS private keys securely (HSM recommended for production)
- Use dedicated machines for node operation
- Keep software updated
- Monitor node logs for anomalies
- Use firewalls to restrict P2P port access

### For Protocol Integrators

- Implement `ISentinel` interface correctly
- Test pause/unpause functionality thoroughly
- Set appropriate access controls on `unpause()`
- Monitor `SentinelShield` bounty deposits

## Known Security Considerations

### Smart Contracts

- BLS signature verification uses BN254 precompiles (EIP-196, EIP-197)
- Optimistic verification has 48-hour dispute window
- 21-day unstaking cooldown prevents stake-and-slash attacks

### Node Software

- gRPC connections to inference server are unencrypted by default
- P2P gossip messages are signed but not encrypted
- Local heuristic fallback may have different detection rates

### AI/ML Model

- Model trained on historical exploits may not detect novel attacks
- Adversarial inputs could potentially evade detection
- False positives trigger 48-hour bounty dispute process

## Audits

Audit reports will be published in `/audits` directory once completed.

## Contact

- Security issues: `security@aegis-network.io`
- General questions: Open a GitHub Discussion

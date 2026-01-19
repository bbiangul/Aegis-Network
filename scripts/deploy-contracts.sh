#!/bin/bash
# =============================================================================
# AEGIS NETWORK - CONTRACT DEPLOYMENT SCRIPT
# =============================================================================
# Usage: ./scripts/deploy-contracts.sh [network]
# Networks: anvil (local), sepolia (testnet), mainnet (production)
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default to anvil (local) if no network specified
NETWORK=${1:-anvil}

echo -e "${GREEN}=== AEGIS NETWORK CONTRACT DEPLOYMENT ===${NC}"
echo ""
echo "Network: $NETWORK"
echo ""

# Load environment variables
if [ -f .env ]; then
    source .env
else
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Copy .env.example to .env and fill in your values"
    exit 1
fi

# Change to sentinel-core directory
cd packages/sentinel-core

# Create deployments directory if it doesn't exist
mkdir -p deployments

case $NETWORK in
    anvil)
        echo -e "${YELLOW}Starting local Anvil node...${NC}"

        # Check if anvil is already running
        if lsof -i:8545 > /dev/null 2>&1; then
            echo "Anvil already running on port 8545"
        else
            anvil --fork-url $ETH_RPC_URL &
            ANVIL_PID=$!
            sleep 3
            echo "Anvil started with PID: $ANVIL_PID"
        fi

        # Use Anvil's default private key for local testing
        export DEPLOYER_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

        echo -e "${GREEN}Deploying to local Anvil...${NC}"
        forge script script/Deploy.s.sol:Deploy \
            --rpc-url http://localhost:8545 \
            --broadcast \
            -vvv

        echo -e "${GREEN}Running simulation...${NC}"
        forge script script/DeployAndSimulate.s.sol:DeployAndSimulate \
            --rpc-url http://localhost:8545 \
            --broadcast \
            -vvv
        ;;

    sepolia)
        # Validate required environment variables
        if [ -z "$SEPOLIA_RPC_URL" ]; then
            echo -e "${RED}Error: SEPOLIA_RPC_URL not set${NC}"
            exit 1
        fi

        if [ -z "$DEPLOYER_PRIVATE_KEY" ]; then
            echo -e "${RED}Error: DEPLOYER_PRIVATE_KEY not set${NC}"
            exit 1
        fi

        echo -e "${GREEN}Deploying to Sepolia testnet...${NC}"
        echo -e "${YELLOW}This will cost testnet ETH. Make sure you have Sepolia ETH.${NC}"
        echo ""

        # Check balance
        DEPLOYER_ADDRESS=$(cast wallet address $DEPLOYER_PRIVATE_KEY)
        BALANCE=$(cast balance $DEPLOYER_ADDRESS --rpc-url $SEPOLIA_RPC_URL)
        echo "Deployer: $DEPLOYER_ADDRESS"
        echo "Balance: $BALANCE wei"
        echo ""

        read -p "Continue with deployment? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 0
        fi

        # Deploy contracts
        forge script script/Deploy.s.sol:Deploy \
            --rpc-url $SEPOLIA_RPC_URL \
            --broadcast \
            --verify \
            -vvv

        echo ""
        echo -e "${GREEN}Deployment complete!${NC}"
        echo "Contract addresses saved to: deployments/sepolia.json"
        echo ""
        echo "Next steps:"
        echo "1. Update your .env with the contract addresses"
        echo "2. Run: ./scripts/deploy-contracts.sh sepolia-setup"
        ;;

    sepolia-setup)
        # Setup testnet with nodes and protocols
        if [ -z "$SENTINEL_TOKEN_ADDRESS" ]; then
            echo -e "${RED}Error: Contract addresses not set in .env${NC}"
            echo "Run deployment first, then update .env with the addresses"
            exit 1
        fi

        echo -e "${GREEN}Setting up testnet environment...${NC}"
        forge script script/Deploy.s.sol:SetupTestnet \
            --rpc-url $SEPOLIA_RPC_URL \
            --broadcast \
            -vvv
        ;;

    mainnet)
        echo -e "${RED}WARNING: MAINNET DEPLOYMENT${NC}"
        echo "This will deploy to Ethereum mainnet and cost real ETH!"
        echo ""
        echo -e "${YELLOW}Checklist:${NC}"
        echo "[ ] All tests passing"
        echo "[ ] Security audit completed"
        echo "[ ] Multi-sig wallet configured"
        echo "[ ] Deployment reviewed by team"
        echo ""
        read -p "Are you sure? Type 'DEPLOY MAINNET' to continue: " -r
        echo
        if [[ ! $REPLY == "DEPLOY MAINNET" ]]; then
            echo "Cancelled."
            exit 0
        fi

        forge script script/Deploy.s.sol:Deploy \
            --rpc-url $ETH_RPC_URL \
            --broadcast \
            --verify \
            --slow \
            -vvv
        ;;

    *)
        echo -e "${RED}Unknown network: $NETWORK${NC}"
        echo "Usage: ./scripts/deploy-contracts.sh [anvil|sepolia|sepolia-setup|mainnet]"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Done!${NC}"

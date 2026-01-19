package config

import (
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/spf13/viper"
)

type Config struct {
	Node      NodeConfig      `mapstructure:"node"`
	Ethereum  EthereumConfig  `mapstructure:"ethereum"`
	P2P       P2PConfig       `mapstructure:"p2p"`
	Inference InferenceConfig `mapstructure:"inference"`
	Contracts ContractConfig  `mapstructure:"contracts"`
	Logging   LoggingConfig   `mapstructure:"logging"`
}

type NodeConfig struct {
	Name           string        `mapstructure:"name"`
	DataDir        string        `mapstructure:"dataDir"`
	PrivateKeyPath string        `mapstructure:"privateKeyPath"`
	BLSKeyPath     string        `mapstructure:"blsKeyPath"`
	MetricsPort    int           `mapstructure:"metricsPort"`
	APIPort        int           `mapstructure:"apiPort"`
	ShutdownTimeout time.Duration `mapstructure:"shutdownTimeout"`
}

type EthereumConfig struct {
	RPCURL             string        `mapstructure:"rpcUrl"`
	WSURL              string        `mapstructure:"wsUrl"`
	FlashbotsRPCURL    string        `mapstructure:"flashbotsRpcUrl"`  // FIX: MEV protection
	ChainID            int64         `mapstructure:"chainId"`
	BlockConfirmations int           `mapstructure:"blockConfirmations"`
	TxTimeout          time.Duration `mapstructure:"txTimeout"`
	MaxGasPrice        int64         `mapstructure:"maxGasPrice"`
	UseMEVProtection   bool          `mapstructure:"useMevProtection"` // FIX: Enable MEV protection
}

type P2PConfig struct {
	ListenAddresses []string      `mapstructure:"listenAddresses"`
	BootstrapPeers  []string      `mapstructure:"bootstrapPeers"`
	MaxPeers        int           `mapstructure:"maxPeers"`
	TopicName       string        `mapstructure:"topicName"`
	HeartbeatInterval time.Duration `mapstructure:"heartbeatInterval"`
}

type InferenceConfig struct {
	GRPCAddress     string        `mapstructure:"grpcAddress"`
	Timeout         time.Duration `mapstructure:"timeout"`
	BatchSize       int           `mapstructure:"batchSize"`
	EnableSimulation bool         `mapstructure:"enableSimulation"`
	AnomalyThreshold float64      `mapstructure:"anomalyThreshold"`
}

type ContractConfig struct {
	TokenAddress    common.Address `mapstructure:"tokenAddress"`
	RegistryAddress common.Address `mapstructure:"registryAddress"`
	ShieldAddress   common.Address `mapstructure:"shieldAddress"`
	RouterAddress   common.Address `mapstructure:"routerAddress"`
}

type LoggingConfig struct {
	Level      string `mapstructure:"level"`
	Format     string `mapstructure:"format"`
	OutputPath string `mapstructure:"outputPath"`
}

func Load(configPath string) (*Config, error) {
	viper.SetConfigFile(configPath)
	viper.SetConfigType("yaml")

	viper.SetDefault("node.name", "sentinel-node")
	viper.SetDefault("node.dataDir", "./data")
	viper.SetDefault("node.metricsPort", 9090)
	viper.SetDefault("node.apiPort", 8080)
	viper.SetDefault("node.shutdownTimeout", 30*time.Second)

	viper.SetDefault("ethereum.chainId", 1)
	viper.SetDefault("ethereum.blockConfirmations", 1)
	viper.SetDefault("ethereum.txTimeout", 5*time.Minute)
	viper.SetDefault("ethereum.maxGasPrice", 500_000_000_000)
	viper.SetDefault("ethereum.flashbotsRpcUrl", "https://relay.flashbots.net")
	viper.SetDefault("ethereum.useMevProtection", true)  // FIX: Enable MEV protection by default

	viper.SetDefault("p2p.listenAddresses", []string{"/ip4/0.0.0.0/tcp/9000"})
	viper.SetDefault("p2p.maxPeers", 50)
	viper.SetDefault("p2p.topicName", "sentinel/v1/alerts")
	viper.SetDefault("p2p.heartbeatInterval", 10*time.Second)

	viper.SetDefault("inference.grpcAddress", "localhost:50051")
	viper.SetDefault("inference.timeout", 300*time.Millisecond)
	viper.SetDefault("inference.batchSize", 10)
	viper.SetDefault("inference.enableSimulation", true)
	viper.SetDefault("inference.anomalyThreshold", 0.65)

	viper.SetDefault("logging.level", "info")
	viper.SetDefault("logging.format", "json")
	viper.SetDefault("logging.outputPath", "stdout")

	if err := viper.ReadInConfig(); err != nil {
		return nil, err
	}

	var config Config
	if err := viper.Unmarshal(&config); err != nil {
		return nil, err
	}

	return &config, nil
}

func LoadFromEnv() (*Config, error) {
	viper.AutomaticEnv()
	viper.SetEnvPrefix("SENTINEL")

	config := &Config{
		Node: NodeConfig{
			Name:            viper.GetString("NODE_NAME"),
			DataDir:         viper.GetString("DATA_DIR"),
			PrivateKeyPath:  viper.GetString("PRIVATE_KEY_PATH"),
			BLSKeyPath:      viper.GetString("BLS_KEY_PATH"),
			MetricsPort:     viper.GetInt("METRICS_PORT"),
			APIPort:         viper.GetInt("API_PORT"),
			ShutdownTimeout: viper.GetDuration("SHUTDOWN_TIMEOUT"),
		},
		Ethereum: EthereumConfig{
			RPCURL:             viper.GetString("ETH_RPC_URL"),
			WSURL:              viper.GetString("ETH_WS_URL"),
			ChainID:            viper.GetInt64("ETH_CHAIN_ID"),
			BlockConfirmations: viper.GetInt("BLOCK_CONFIRMATIONS"),
			TxTimeout:          viper.GetDuration("TX_TIMEOUT"),
			MaxGasPrice:        viper.GetInt64("MAX_GAS_PRICE"),
		},
		P2P: P2PConfig{
			ListenAddresses:   viper.GetStringSlice("P2P_LISTEN"),
			BootstrapPeers:    viper.GetStringSlice("P2P_BOOTSTRAP"),
			MaxPeers:          viper.GetInt("P2P_MAX_PEERS"),
			TopicName:         viper.GetString("P2P_TOPIC"),
			HeartbeatInterval: viper.GetDuration("P2P_HEARTBEAT"),
		},
		Inference: InferenceConfig{
			GRPCAddress:      viper.GetString("INFERENCE_GRPC"),
			Timeout:          viper.GetDuration("INFERENCE_TIMEOUT"),
			BatchSize:        viper.GetInt("INFERENCE_BATCH_SIZE"),
			EnableSimulation: viper.GetBool("ENABLE_SIMULATION"),
			AnomalyThreshold: viper.GetFloat64("ANOMALY_THRESHOLD"),
		},
		Logging: LoggingConfig{
			Level:      viper.GetString("LOG_LEVEL"),
			Format:     viper.GetString("LOG_FORMAT"),
			OutputPath: viper.GetString("LOG_OUTPUT"),
		},
	}

	return config, nil
}

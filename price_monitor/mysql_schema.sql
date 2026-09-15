-- Packaged copy of the MySQL 8 schema used when Price Monitor is installed as a wheel.

CREATE TABLE IF NOT EXISTS price_observations (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  product ENUM('gasoil','brent','bitume') NOT NULL,
  price DECIMAL(14,4) NOT NULL,
  unit VARCHAR(32) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD',
  source VARCHAR(150) NOT NULL,
  source_date DATE NOT NULL,
  collected_at DATETIME NOT NULL,
  variation DECIMAL(14,6) NULL,
  variation_pct DECIMAL(10,4) NULL,
  is_unchanged BOOLEAN NOT NULL DEFAULT FALSE,
  notes VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_observation_identity (product, source, source_date, price),
  INDEX idx_product_collected (product, collected_at)
);

CREATE TABLE IF NOT EXISTS data_sources (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  label VARCHAR(120) NOT NULL,
  provider VARCHAR(160) NOT NULL,
  frequency VARCHAR(32) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  last_success_at DATETIME NULL,
  last_error VARCHAR(500) NULL
);

CREATE TABLE IF NOT EXISTS collection_logs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status ENUM('success','partial','error') NOT NULL,
  rows_collected INT NOT NULL DEFAULT 0,
  message VARCHAR(500) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(32) PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_states (
  alert_key VARCHAR(191) PRIMARY KEY,
  active BOOLEAN NOT NULL DEFAULT FALSE,
  last_value DECIMAL(14,4) NULL,
  last_notified_at DATETIME NULL,
  updated_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS procurement_purchases (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  product ENUM('gasoil','brent','bitume') NOT NULL,
  supplier VARCHAR(150) NOT NULL,
  quantity DECIMAL(18,6) NOT NULL,
  unit VARCHAR(32) NOT NULL,
  currency CHAR(3) NOT NULL,
  unit_price DECIMAL(18,6) NOT NULL,
  exchange_rate DECIMAL(18,8) NOT NULL,
  transport_cost DECIMAL(18,6) NOT NULL DEFAULT 0,
  budget_amount DECIMAL(18,6) NULL,
  purchase_date DATE NOT NULL,
  total_cost DECIMAL(18,6) NOT NULL,
  total_cost_usd DECIMAL(18,6) NOT NULL,
  budget_variance DECIMAL(18,6) NULL,
  budget_variance_usd DECIMAL(18,6) NULL,
  market_price_usd DECIMAL(18,6) NULL,
  price_impact_unit_usd DECIMAL(18,6) NULL,
  price_impact_total_usd DECIMAL(18,6) NULL,
  price_impact_pct DECIMAL(12,4) NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_procurement_purchase_date (purchase_date, product)
);

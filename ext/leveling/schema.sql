-- Leveling schema
CREATE TABLE IF NOT EXISTS leveling (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT DEFAULT 0,
    message TEXT,
    multiplier REAL DEFAULT 1.0,
    booster REAL DEFAULT 1.0,
    stack BOOLEAN DEFAULT FALSE,
    command BOOLEAN DEFAULT TRUE,
    voice_multiplier REAL DEFAULT 1.0,
    voice_booster REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS level_user (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    xp BIGINT DEFAULT 0,
    level INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_multipliers (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    multiplier REAL NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    level INT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

-- Leveling system tables
-- Run these once on the bot database

CREATE TABLE IF NOT EXISTS leveling (
    guild_id        BIGINT PRIMARY KEY,
    message         TEXT DEFAULT 'Nice work {user.mention} - you reached **Level {level}**!',
    message_rolegain TEXT DEFAULT NULL,
    channel_id      BIGINT,
    multiplier      REAL DEFAULT 1.0,
    booster         REAL DEFAULT 1.0,
    voice_multiplier REAL DEFAULT 1.0,
    voice_booster   REAL DEFAULT 1.0,
    stack           BOOLEAN DEFAULT FALSE,
    command         BOOLEAN DEFAULT FALSE,
    roles           TEXT DEFAULT '[]',
    channels        TEXT DEFAULT '[]',
    users           TEXT DEFAULT '[]',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE leveling ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE leveling ADD COLUMN IF NOT EXISTS message_rolegain TEXT DEFAULT NULL;

CREATE TABLE IF NOT EXISTS level_user (
    guild_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    xp          REAL DEFAULT 0,
    level       INT DEFAULT 1,
    target_xp   INT DEFAULT 100,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_multiplier (
    guild_id    BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    multiplier  REAL NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS level_multiplier_voice (
    guild_id    BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    multiplier  REAL NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id    BIGINT NOT NULL,
    level       INT NOT NULL,
    role_id     BIGINT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_level_user_guild ON level_user (guild_id);
CREATE INDEX IF NOT EXISTS idx_level_rewards_guild ON level_rewards (guild_id);

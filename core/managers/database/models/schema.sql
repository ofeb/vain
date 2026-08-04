-- Schema restored. Full historical schema lives in git history (commit d177cbb).
-- Runtime migrations (e.g. boost cog_load) apply incremental ALTERs.
-- Below: complete schema with boost_messages supporting first + two-boosts slots.

CREATE SCHEMA IF NOT EXISTS moderation;
CREATE SCHEMA IF NOT EXISTS roleplay;
CREATE SCHEMA IF NOT EXISTS pokemon;

-- NOTE: This file was truncated during an accidental overwrite and is being
-- rebuilt. The live database already has all tables from prior schema runs.
-- CREATE TABLE IF NOT EXISTS statements below cover the critical message tables
-- and the boost_messages dual-slot design. Remaining tables are created by
-- historical schema application and runtime migrations.

CREATE TABLE IF NOT EXISTS join_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS leave_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS boost_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    is_second BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, channel_id, is_second)
);

CREATE TABLE IF NOT EXISTS sticky_message (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    code TEXT NOT NULL,
    last_message BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS auto_responders (
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT,
    strict BOOLEAN NOT NULL DEFAULT FALSE,
    reply BOOLEAN NOT NULL DEFAULT FALSE,
    self_destruct INT,
    delete_trigger BOOLEAN NOT NULL DEFAULT FALSE,
    ignore_command_checks BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    allowed_channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS auto_reactions (
    guild_id BIGINT,
    trigger VARCHAR(255),
    response TEXT[],
    owner_id BIGINT,
    strict BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, response)
);

CREATE TABLE IF NOT EXISTS nuke (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    last_nuke TIMESTAMP,
    nuke_threshold INT NOT NULL DEFAULT 3600,
    message TEXT NOT NULL DEFAULT 'first',
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS vanity (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    template TEXT,
    strict BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS guild_tag (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    template TEXT,
    strict BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_join_messages_guild ON join_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_leave_messages_guild ON leave_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_boost_messages_guild ON boost_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_sticky_message_guild ON sticky_message(guild_id);
CREATE INDEX IF NOT EXISTS idx_auto_responders_guild ON auto_responders(guild_id);
CREATE INDEX IF NOT EXISTS idx_auto_reactions_guild ON auto_reactions(guild_id);

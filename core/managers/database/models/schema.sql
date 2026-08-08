CREATE SCHEMA IF NOT EXISTS moderation;
CREATE SCHEMA IF NOT EXISTS roleplay;
CREATE SCHEMA IF NOT EXISTS pokemon;

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
    message_limit INT NOT NULL DEFAULT 1,
    interval_seconds INT NOT NULL DEFAULT 0,
    message_count INT NOT NULL DEFAULT 0,
    last_sent TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS crypto_feeds (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    coin_id TEXT NOT NULL,
    coin_label TEXT NOT NULL,
    last_price DOUBLE PRECISION,
    last_change DOUBLE PRECISION,
    last_market_cap DOUBLE PRECISION,
    last_posted TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, coin_id)
);
CREATE INDEX IF NOT EXISTS idx_crypto_feeds_coin ON crypto_feeds(coin_id);

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

CREATE SCHEMA IF NOT EXISTS monitor;

CREATE TABLE IF NOT EXISTS monitor.tiktok (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    live_template TEXT,
    reposts BOOLEAN NOT NULL DEFAULT FALSE,
    lives BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.instagram (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    stories BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.twitter (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    retweets BOOLEAN NOT NULL DEFAULT TRUE,
    replies BOOLEAN NOT NULL DEFAULT FALSE,
    quotes BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.youtube (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    shorts BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.twitch (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.pinterest (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    board_id TEXT NOT NULL DEFAULT '',
    board_name TEXT,
    template TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, board_id)
);

CREATE TABLE IF NOT EXISTS monitor.snapchat (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    template TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.seen (
    platform TEXT NOT NULL,
    item_id TEXT NOT NULL,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, item_id)
);

CREATE INDEX IF NOT EXISTS idx_monitor_tiktok_guild ON monitor.tiktok(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_instagram_guild ON monitor.instagram(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_twitter_guild ON monitor.twitter(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_youtube_guild ON monitor.youtube(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_twitch_guild ON monitor.twitch(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_pinterest_guild ON monitor.pinterest(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_snapchat_guild ON monitor.snapchat(guild_id);

CREATE TABLE IF NOT EXISTS guilds (
    guild_id BIGINT PRIMARY KEY,
    prefix VARCHAR(10) DEFAULT ';',
    language VARCHAR(5) DEFAULT 'en',
    muted_role_id BIGINT,
    auto_role_id BIGINT,
    welcome_channel_id BIGINT,
    welcome_message TEXT,
    leave_channel_id BIGINT,
    leave_message TEXT,
    boost_channel_id BIGINT,
    boost_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT,
    guild_id BIGINT,
    balance BIGINT DEFAULT 0,
    xp BIGINT DEFAULT 0,
    level INT DEFAULT 0,
    warnings INT DEFAULT 0,
    muted_until TIMESTAMP,
    birthday VARCHAR(20),
    timezone VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS moderation (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    action_type VARCHAR(20),
    reason TEXT,
    duration VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS highlights (
    guild_id BIGINT,
    user_id BIGINT,
    keyword VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, keyword)
);

CREATE TABLE IF NOT EXISTS highlight_ignores (
    guild_id BIGINT,
    user_id BIGINT,
    target_id BIGINT,
    target_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, target_id, target_type)
);

CREATE TABLE IF NOT EXISTS sticky_roles (
    guild_id BIGINT,
    user_id BIGINT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, role_id)
);

CREATE TABLE IF NOT EXISTS forced_nicknames (
    guild_id BIGINT,
    user_id BIGINT,
    nickname VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS restricted_commands (
    guild_id BIGINT,
    command_name VARCHAR(50),
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command_name, role_id)
);

CREATE TABLE IF NOT EXISTS roblox_links (
    discord_id BIGINT PRIMARY KEY,
    roblox_id BIGINT,
    username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS snapchat_links (
    discord_id BIGINT PRIMARY KEY,
    snapchat_username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    message TEXT,
    time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS proofs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    case_id INT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auto_reactions (
    guild_id BIGINT,
    trigger VARCHAR(255),
    response TEXT[],
    owner_id BIGINT,
    strict BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, response)
);

CREATE TABLE IF NOT EXISTS reaction_history (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    user_id BIGINT,
    reaction VARCHAR(255),
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auto_role (
    guild_id BIGINT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS button_roles (
    guild_id BIGINT,
    message_id BIGINT,
    channel_id BIGINT,
    role_id BIGINT,
    style VARCHAR(20),
    emoji VARCHAR(255),
    label VARCHAR(100),
    index INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reaction_role (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, role_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    prize VARCHAR(255),
    expiration TIMESTAMP,
    winner_count INT DEFAULT 1,
    hosts BIGINT[],
    entries BIGINT[],
    max_level INT,
    min_level INT,
    required_roles BIGINT[],
    win_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id)
);

CREATE TABLE IF NOT EXISTS counters (
    guild_id BIGINT,
    channel_id BIGINT,
    counter_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, counter_type)
);

CREATE TABLE IF NOT EXISTS clownboard (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    emoji VARCHAR(255),
    threshold INT DEFAULT 1,
    lock BOOLEAN DEFAULT FALSE,
    ignore_entries TEXT,
    attachments BOOLEAN DEFAULT FALSE,
    ts BOOLEAN DEFAULT FALSE,
    jump BOOLEAN DEFAULT FALSE,
    self_star BOOLEAN DEFAULT TRUE,
    color VARCHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clownboard_entries (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    clownboard_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS starboard (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    emoji VARCHAR(255),
    threshold INT DEFAULT 1,
    lock BOOLEAN DEFAULT FALSE,
    ignore_entries TEXT,
    attachments BOOLEAN DEFAULT FALSE,
    ts BOOLEAN DEFAULT FALSE,
    jump BOOLEAN DEFAULT FALSE,
    self_star BOOLEAN DEFAULT TRUE,
    color VARCHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS starboard_entries (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    starboard_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS voicemaster_configuration (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    category_id BIGINT,
    role_id BIGINT,
    bitrate INT,
    region VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voicemaster_channels (
    guild_id BIGINT,
    channel_id BIGINT,
    owner_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id)
);

CREATE TABLE IF NOT EXISTS tictactoe (
    user_id BIGINT PRIMARY KEY,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    ties INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS birthday (
    user_id BIGINT,
    guild_id BIGINT,
    birthday_date DATE,
    timezone VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS birthday_notifications (
    guild_id BIGINT,
    channel_id BIGINT,
    message TEXT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS level_config (
    guild_id BIGINT PRIMARY KEY,
    enabled BOOLEAN DEFAULT TRUE,
    multiplier INT DEFAULT 1,
    message TEXT,
    role_rewards JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id BIGINT,
    level INT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS bump_reminder (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_id BIGINT,
    message TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crypto_alerts (
    user_id BIGINT,
    guild_id BIGINT,
    coin VARCHAR(50),
    threshold DECIMAL(20, 8),
    above BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id, coin, threshold)
);

CREATE TABLE IF NOT EXISTS lastfm (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS social_links (
    user_id BIGINT,
    platform VARCHAR(50),
    link TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, platform)
);

CREATE TABLE IF NOT EXISTS timers (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    name VARCHAR(100),
    time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emoji_usage (
    guild_id BIGINT,
    emoji_id BIGINT,
    emoji_name VARCHAR(100),
    uses INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, emoji_id)
);

CREATE TABLE IF NOT EXISTS invocation (
    guild_id BIGINT,
    command VARCHAR(50),
    dm_code TEXT,
    message_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command)
);

CREATE INDEX IF NOT EXISTS idx_moderation_guild_user ON moderation(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_highlights_guild ON highlights(guild_id);
CREATE INDEX IF NOT EXISTS idx_highlight_ignores_guild ON highlight_ignores(guild_id);
CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(time);
CREATE INDEX IF NOT EXISTS idx_notes_guild_user ON notes(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_auto_reactions_guild ON auto_reactions(guild_id);
CREATE INDEX IF NOT EXISTS idx_reaction_history_message ON reaction_history(message_id);
CREATE INDEX IF NOT EXISTS idx_button_roles_guild ON button_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_reaction_role_guild ON reaction_role(guild_id);
CREATE INDEX IF NOT EXISTS idx_giveaways_guild ON giveaways(guild_id);
CREATE INDEX IF NOT EXISTS idx_counters_guild ON counters(guild_id);
CREATE INDEX IF NOT EXISTS idx_clownboard_entries_guild ON clownboard_entries(guild_id);
CREATE INDEX IF NOT EXISTS idx_starboard_entries_guild ON starboard_entries(guild_id);
CREATE INDEX IF NOT EXISTS idx_voicemaster_channels_guild ON voicemaster_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_birthday_guild ON birthday(guild_id);
CREATE INDEX IF NOT EXISTS idx_birthday_user ON birthday(user_id);
CREATE INDEX IF NOT EXISTS idx_level_roles_guild ON level_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_crypto_alerts_user ON crypto_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_links_user ON social_links(user_id);
CREATE INDEX IF NOT EXISTS idx_timers_time ON timers(time);

CREATE INDEX IF NOT EXISTS idx_emoji_usage_guild ON emoji_usage(guild_id);
CREATE INDEX IF NOT EXISTS idx_invocation_guild ON invocation(guild_id);

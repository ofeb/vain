DISBOARD_ID = 302050872383242240
BUMP_COOLDOWN = 7200  


DEFAULT_REMINDER_SCRIPT = (
    "{container}"
    "$v{content: {bumper.mention}}"
    "$v{description: **Time to bump**\n\n"
    "The **Disboard** cooldown is over - **{guild.name}** is **falling off** the list.\n\n"
    "Run </bump:947088344167366698> to **keep {guild.name} on the list**.\n\n"
    "> -# **Last bumped by**: {bumper_label}\n"
    "> -# **Last bumped at**: {last_bump_ts}}"
)

DEFAULT_THANKYOU_SCRIPT = (
    "{container}"
    "$v{description: > **{guild.name}** was bumped!**\n\n"
    "> Thanks {bumper.mention} - **{guild.name}** is **back** on the **Disboard** list.\n\n"
    "> Next reminder**: {next_bump_ts}}"
)

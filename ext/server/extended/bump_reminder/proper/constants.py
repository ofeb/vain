DISBOARD_ID = 302050872383242240
BUMP_COOLDOWN = 7200  


DEFAULT_REMINDER_SCRIPT = (
    "{container}"
    "$v{content: {bumper.mention}}"
    "$v{description: **__Time to bump__**\n"
    "The **Disboard** cooldown is over - this guild is falling off the list.\n\n"
    "Run </bump:947088344167366698> to keep this guild on the list.\n\n"
    "-# Last bump · {bumper_label} · {last_bump_ts}}"
)

DEFAULT_THANKYOU_SCRIPT = (
    "{container}"
    "$v{description: **__Bump logged__**\n"
    "Thanks {bumper.mention} - **{guild.name}** is back on the Disboard list.\n\n"
    "-# Next reminder · {next_bump_ts}}"
)

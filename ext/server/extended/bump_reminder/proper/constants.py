DISBOARD_ID = 302050872383242240
BUMP_COOLDOWN = 7200  


DEFAULT_REMINDER_SCRIPT = (
    "{container}"
    "$v{content: {bumper.mention}}"
    "$v{description: # Time to promote\n"
    "**Disboard** is ready for another bump.\n\n"
    "Run </bump:947088344167366698> to keep this guild on the list.\n\n"
    "-# Last bump · {bumper.display} · <t:{timestamp}:R>}"
)

DEFAULT_THANKYOU_SCRIPT = (
    "{container}"
    "$v{description: # Bump logged\n"
    "Thanks {bumper.mention} — this guild is back on **Disboard**.\n\n"
    "-# Next reminder in **2 hours** · <t:{timestamp}:R>}"
)

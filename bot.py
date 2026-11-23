import os
import re
from pathlib import Path
import aiohttp
import discord
from aiohttp import web
from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands, tasks

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL_LOGIN = os.getenv("TWITCH_CHANNEL_LOGIN", "").strip().lower()
TWITCH_ANNOUNCEMENT_CHANNEL_ID = os.getenv("TWITCH_ANNOUNCEMENT_CHANNEL_ID")
LAST_STREAM_FILE = Path(__file__).with_name(".last_announced_stream")

intents = discord.Intents.default()
intents.members = True
_health_server = None


async def health_check(_request: web.Request) -> web.Response:
    return web.Response(text="Funnyahh bot is running.", content_type="text/plain")


async def start_health_server():
    global _health_server
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    _health_server = web.AppRunner(app)
    await _health_server.setup()
    site = web.TCPSite(_health_server, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()
    print("Health endpoint is listening.")


class StreamerBot(commands.Bot):
    async def setup_hook(self):
        await start_health_server()
        if not keep_render_awake.is_running():
            keep_render_awake.start()


bot = StreamerBot(command_prefix="!", intents=intents)
_twitch_token = None
_twitch_token_expires_at = 0
_twitch_status = None
_twitch_config_warning_logged = False


async def get_twitch_token(session: aiohttp.ClientSession) -> str:
    global _twitch_token, _twitch_token_expires_at
    if _twitch_token and discord.utils.utcnow().timestamp() < _twitch_token_expires_at - 60:
        return _twitch_token

    async with session.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    ) as response:
        response.raise_for_status()
        data = await response.json()
    _twitch_token = data["access_token"]
    _twitch_token_expires_at = discord.utils.utcnow().timestamp() + data["expires_in"]
    return _twitch_token


@tasks.loop(seconds=20)
async def check_twitch_live():
    global _twitch_status, _twitch_config_warning_logged
    if not all((TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_CHANNEL_LOGIN, TWITCH_ANNOUNCEMENT_CHANNEL_ID)):
        if not _twitch_config_warning_logged:
            missing = [
                name for name, value in (
                    ("TWITCH_CLIENT_ID", TWITCH_CLIENT_ID),
                    ("TWITCH_CLIENT_SECRET", TWITCH_CLIENT_SECRET),
                    ("TWITCH_CHANNEL_LOGIN", TWITCH_CHANNEL_LOGIN),
                    ("TWITCH_ANNOUNCEMENT_CHANNEL_ID", TWITCH_ANNOUNCEMENT_CHANNEL_ID),
                ) if not value
            ]
            print(f"Twitch alerts are not configured; missing: {', '.join(missing)}")
            _twitch_config_warning_logged = True
        return
    _twitch_config_warning_logged = False

    try:
        async with aiohttp.ClientSession() as session:
            token = await get_twitch_token(session)
            headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
            async with session.get(
                "https://api.twitch.tv/helix/streams",
                params={"user_login": TWITCH_CHANNEL_LOGIN},
                headers=headers,
            ) as response:
                response.raise_for_status()
                data = await response.json()

        streams = data.get("data", [])
        if not streams:
            if _twitch_status != "offline":
                print(f"Twitch channel {TWITCH_CHANNEL_LOGIN} is currently offline.")
            _twitch_status = "offline"
            return

        stream = streams[0]
        stream_id = str(stream["id"])
        try:
            last_stream_id = LAST_STREAM_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            last_stream_id = ""
        if stream_id == last_stream_id:
            if _twitch_status != "already_announced":
                print(f"Twitch channel {TWITCH_CHANNEL_LOGIN} is live; this stream was already announced.")
            _twitch_status = "already_announced"
            return

        channel = bot.get_channel(int(TWITCH_ANNOUNCEMENT_CHANNEL_ID))
        if channel is None:
            channel = await bot.fetch_channel(int(TWITCH_ANNOUNCEMENT_CHANNEL_ID))
        twitch_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_LOGIN}"
        title = stream.get("title") or "A new stream is live!"
        game = stream.get("game_name")
        description = f"**{title}**"
        if game:
            description += f"\n\n🎮 **Playing:** {game}"
        description += "\n\nCome hang out in chat!"

        embed = discord.Embed(
            title=f"🔴 {TWITCH_CHANNEL_LOGIN} is LIVE!",
            url=twitch_url,
            description=description,
            color=discord.Colour.from_rgb(145, 70, 255),
        )
        thumbnail_url = stream.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")
        if thumbnail_url:
            embed.set_image(url=thumbnail_url)
        embed.set_footer(text="LIVE NOW ON TWITCH")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Watch on Twitch", url=twitch_url))
        await channel.send(
            "@everyone",
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False),
        )
        LAST_STREAM_FILE.write_text(stream_id, encoding="utf-8")
        _twitch_status = "announced"
        print(f"Posted Twitch live alert for {TWITCH_CHANNEL_LOGIN}.")
    except (aiohttp.ClientError, discord.HTTPException, ValueError, KeyError) as exc:
        print(f"Twitch live check failed: {exc}")


@tasks.loop(minutes=10)
async def keep_render_awake():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{render_url.rstrip('/')}/health") as response:
                response.raise_for_status()
        print("Render keepalive ping succeeded.")
    except (aiohttp.ClientError, TimeoutError) as exc:
        print(f"Render keepalive ping failed: {exc}")


@check_twitch_live.before_loop
async def before_check_twitch_live():
    await bot.wait_until_ready()


def safe_slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")[:80] or "streamer"


async def ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    existing = discord.utils.get(guild.categories, name=name)
    return existing or await guild.create_category(name, reason="Streamer server setup")


async def ensure_text(guild: discord.Guild, name: str, category: discord.CategoryChannel, topic: str = "") -> discord.TextChannel:
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing:
        if existing.category != category:
            await existing.edit(category=category, reason="Organize streamer server")
        return existing
    return await guild.create_text_channel(name, category=category, topic=topic or None, reason="Streamer server setup")


async def ensure_voice(guild: discord.Guild, name: str, category: discord.CategoryChannel) -> discord.VoiceChannel:
    existing = discord.utils.get(guild.voice_channels, name=name)
    if existing:
        if existing.category != category:
            await existing.edit(category=category, reason="Organize streamer server")
        return existing
    return await guild.create_voice_channel(name, category=category, reason="Streamer server setup")


async def ensure_role(guild: discord.Guild, name: str, color: discord.Colour) -> discord.Role:
    existing = discord.utils.get(guild.roles, name=name)
    return existing or await guild.create_role(name=name, colour=color, reason="Streamer server setup")


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Logged in as {bot.user}; synced {len(synced)} slash command(s).")
        if not check_twitch_live.is_running():
            check_twitch_live.start()
    except discord.HTTPException as exc:
        print(f"Could not sync slash commands: {exc}")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    channel = discord.utils.get(guild.text_channels, name="welcome")
    if channel is None:
        print(f"Could not greet {member}; #welcome does not exist. Run /setup_server to create it.")
        return

    rules = discord.utils.get(guild.text_channels, name="rules")
    introductions = discord.utils.get(guild.text_channels, name="introductions")
    start_links = []
    if rules:
        start_links.append(f"Read {rules.mention}")
    if introductions:
        start_links.append(f"introduce yourself in {introductions.mention}")

    embed = discord.Embed(
        title=f"Welcome to {guild.name}!",
        description=(
            "We’re glad you’re here. Get comfy, meet the community, and come hang out on stream!"
        ),
        color=discord.Colour.from_rgb(145, 70, 255),
    )
    if start_links:
        embed.add_field(name="Your first stop", value=" • ".join(start_links), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"You’re member #{guild.member_count}")

    await channel.send(
        f"👋 Welcome, {member.mention}!",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )


@bot.tree.command(name="setup_server", description="Create a starter streaming community layout")
@app_commands.describe(channel_name="Your streaming channel or creator name")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True, send_messages=True)
async def setup_server(interaction: discord.Interaction, channel_name: str):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Run this command inside your server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    slug = safe_slug(channel_name)

    # Reuse existing named categories/channels and roles, so rerunning setup is safe.
    welcome = await ensure_category(guild, "WELCOME")
    community = await ensure_category(guild, "COMMUNITY")
    stream = await ensure_category(guild, "LIVE & CONTENT")
    voice = await ensure_category(guild, "VOICE CHAT")

    await ensure_text(guild, "welcome", welcome, "New members are greeted here.")
    rules = await ensure_text(guild, "rules", welcome, "Read this before chatting.")
    await ensure_text(guild, "announcements", welcome, "Official updates from the creator.")
    await ensure_text(guild, "introductions", community, "Say hi and tell everyone what you like to watch.")
    await ensure_text(guild, "general-chat", community, "Chat with the community.")
    await ensure_text(guild, "clips-and-highlights", stream, "Share your favorite stream moments.")
    await ensure_text(guild, "stream-notifications", stream, "Go-live alerts and stream schedules.")
    await ensure_text(guild, "suggestions", community, "Ideas for streams and the community.")
    await ensure_voice(guild, "Community Hangout", voice)
    await ensure_voice(guild, "Live Watch Party", voice)

    await ensure_role(guild, "Stream Team", discord.Colour.purple())
    await ensure_role(guild, "Moderator", discord.Colour.blue())
    await ensure_role(guild, "VIP", discord.Colour.gold())
    await ensure_role(guild, "Community", discord.Colour.teal())

    if not rules.topic or rules.topic == "Read this before chatting.":
        await rules.edit(topic=f"Welcome to {channel_name}'s community. Be kind, keep it respectful, and follow Discord's rules.")

    await interaction.followup.send(
        f"Starter layout is ready for **{channel_name}** in **{guild.name}**.\n"
        f"Created/reused the welcome, community, live content, and voice sections, plus starter roles.\n"
        f"Suggested invite or channel slug: `/{slug}`. You can customize names, rules, and permissions in Server Settings.",
        ephemeral=True,
    )


@setup_server.error
async def setup_server_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to run this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "I need **Manage Channels**, **Manage Roles**, and **Send Messages** permissions."
    else:
        message = "Setup hit an error. Check the bot console for details."
        print(f"setup_server error: {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="rename_channel", description="Rename a text channel in this server")
@app_commands.describe(channel="The text channel to rename", new_name="The channel's new name")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def rename_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    new_name: app_commands.Range[str, 1, 100],
):
    new_name = new_name.strip()
    if not new_name:
        await interaction.response.send_message("Enter a channel name.", ephemeral=True)
        return

    try:
        await channel.edit(name=new_name, reason=f"Renamed by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to rename that channel.", ephemeral=True)
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Discord couldn't rename the channel: {exc}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Renamed the channel to {channel.mention}.", ephemeral=True
    )


@rename_channel.error
async def rename_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need **Manage Channels** permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "I need **Manage Channels** permission to rename channels."
    else:
        message = "I couldn't rename that channel. Check the bot console for details."
        print(f"rename_channel error: {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="rename_server", description="Change this Discord server's name")
@app_commands.describe(new_name="The new name for this server")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_guild=True)
async def rename_server(
    interaction: discord.Interaction,
    new_name: app_commands.Range[str, 1, 100],
):
    guild = interaction.guild
    new_name = new_name.strip()
    if guild is None:
        await interaction.response.send_message("Run this command inside your server.", ephemeral=True)
        return
    if not new_name:
        await interaction.response.send_message("Enter a server name.", ephemeral=True)
        return

    try:
        await guild.edit(name=new_name, reason=f"Server renamed by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to rename this server.", ephemeral=True)
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Discord couldn't rename the server: {exc}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Server name changed to **{guild.name}**.", ephemeral=True
    )


@rename_server.error
async def rename_server_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need **Manage Server** permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "I need **Manage Server** permission to rename the server."
    else:
        message = "I couldn't rename the server. Check the bot console for details."
        print(f"rename_server error: {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if not TOKEN:
    raise RuntimeError("Set DISCORD_TOKEN in your environment before starting the bot.")

bot.run(TOKEN)

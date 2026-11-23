# Streamer Discord Setup Bot

A small Discord bot that adds a starter streaming community layout to a server you already own. Run `/setup_server channel_name: YourChannel` in Discord.

It also has `/rename_channel`, which lets a member with **Manage Channels** choose a text channel and give it a new name, and `/rename_server`, which changes the Discord server name. The bot needs the matching permission for each command. With Twitch credentials configured, it checks your channel every 20 seconds and posts once when a new live stream starts.

It creates or reuses these categories and rooms:

- **WELCOME**: `#welcome`, `#rules`, `#announcements`
- **COMMUNITY**: `#introductions`, `#general-chat`, `#suggestions`
- **LIVE & CONTENT**: `#clips-and-highlights`, `#stream-notifications`
- **VOICE CHAT**: `Community Hangout`, `Live Watch Party`
- **MANAGEMENT**: private `#manage` control panel, visible to the server owner and the `Moderator` role
- Roles: `Stream Team`, `Moderator`, `VIP`, `Community`

The setup command can be rerun; it reuses channels and roles with matching names. It does not delete existing content or assign roles. Review channel permissions and role access in Server Settings after setup.

The private `#manage` panel has buttons to rename the server, choose and rename a text channel, and post a welcome-message preview. Assign the `Moderator` role to each trusted moderator in Server Settings > Roles / Members. Rerun `/setup_server` after updating the bot to create or refresh the panel. Discord's Administrator permission can bypass private-channel visibility, as usual.

## 1. Create a Discord application and bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application.
2. Open **Bot**, add a bot, and copy its token. Keep the token private; never post it in chat or commit it to a repository.
3. In **OAuth2 > URL Generator**, select scopes `bot` and `applications.commands`.
4. Select permissions `Manage Channels`, `Manage Roles`, `Manage Server`, `Send Messages`, `Embed Links`, `Mention @everyone, @here, and All Roles`, and `View Channels`. Open the generated URL and add the bot to your server.
5. The bot role must be above the roles it will manage in the server's role list.

You must create the Discord server yourself first. A bot cannot create a new server on your behalf.

## 2. Install and run

Python 3.10 or newer is recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Put your bot token in `.env`, then start it. To enable Twitch live announcements, also fill in the Twitch and Discord channel values described below.

```powershell
python bot.py
```

Keep the process running while you use the bot. Slash commands may take a short time to appear after the bot starts.

## 3. Set up the server

When the bot starts and is in exactly one server, it automatically creates or reuses the streamer layout. It uses your `TWITCH_CHANNEL_LOGIN` as the creator name, or the server name if Twitch is not configured. If the bot is in multiple servers, run `/setup_server` in the intended server and enter your channel or creator name. You need **Manage Server** permission for that command. Customize rules, channel descriptions, and role access in Server Settings.

The setup creates `#welcome`. When someone joins, the bot posts a purple welcome card with links to `#rules` and `#introductions`. To enable join greetings, open the [Discord Developer Portal](https://discord.com/developers/applications), select your application, open **Bot**, and turn on **Server Members Intent** under **Privileged Gateway Intents**. Save the setting, restart the bot, and rerun `/setup_server` once to create the welcome channel. The bot must have **View Channel**, **Send Messages**, and **Embed Links** in `#welcome`, and it must be online when someone joins.

To rename a text channel, run `/rename_channel`, choose the channel, and enter its new name. Restart the bot process so it syncs the added slash command.

To rename the Discord server, run `/rename_server` and enter the new server name. You need **Manage Server** permission, and the bot needs **Manage Server** permission too.

## 4. Enable Twitch live announcements

1. In the [Twitch Developer Console](https://dev.twitch.tv/console/apps), register an application and copy its Client ID and Client Secret.
2. In `.env`, set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` to those values, and set `TWITCH_CHANNEL_LOGIN` to your Twitch username (the part after `twitch.tv/`).
3. In Discord, enable Developer Mode under **User Settings > Advanced**. Right-click the text channel where alerts should go and choose **Copy Channel ID**. Set that number as `TWITCH_ANNOUNCEMENT_CHANNEL_ID` in `.env`.
4. Make sure the bot can view and send messages in that channel, save `.env`, and restart the bot.

The bot checks Twitch every 20 seconds, so an alert can take up to about 20 seconds to appear. Its console logs whether Twitch is offline, the live stream was already announced, or an alert was posted. Keep the bot process running. The live announcement pings `@everyone`, includes the stream preview and title, and adds a Twitch link button. Make sure the bot has the `Mention @everyone, @here, and All Roles` permission in the alert channel. Do not share or commit the Twitch Client Secret or Discord bot token. The first live stream detected after setup (or a restart if it has not been announced before) will trigger an alert.

## 5. Keep the bot running online

This project includes `render.yaml` for a Render Free web service. The bot exposes `/health` and pings that endpoint every 10 minutes using Render's `RENDER_EXTERNAL_URL`. To deploy it, put this folder in a GitHub repository **without uploading `.env`**, connect the repository to Render as a Blueprint, and enter your five environment values when Render prompts you. The `.gitignore` file excludes `.env` and local Python files. Render's free web services can sleep after 15 minutes without inbound traffic and can restart at any time, so the self-ping is best effort and does not guarantee continuous uptime. See [Render's free service limits](https://render.com/docs/free).

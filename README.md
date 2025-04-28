# **Discord Notification Bot**

A bot for sending notifications to a specific Discord channel when triggered by certain events.<br>
Built using Python and the discord.py library.<br>

## Requirements

- **Python 3.8+**
- **discord.py** library (can be installed via `pip install discord.py`)

## Features

- **Send Notifications**: Send customizable messages to a Discord channel.
- **Environment Variable Configuration**: Configure the bot using environment variables (TOKEN, CHANNEL_ID, ROLE_ID).
- **Error Logging**: Logs errors that occur during execution, helpful for debugging.

## Usage

1. Set up environment variables:
   - `DISCORD_TOKEN`: Your Discord bot token.
   - `CHANNEL_ID`: The ID of the channel where notifications will be sent.
   - `ROLE_ID`: The ID of the role to mention in notifications (optional).

2. Run the bot:

```bash
python bot.py
```
   
Once the bot is running, it will automatically send a notification when the bot is ready and online.

## Installation (for development)

1. Clone the repository:

```bash
git clone https://github.com/cyclonicalperson/discord-notification-bot.git
cd discord-notification-bot
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

Set up environment variables using a .env file or your system's environment.

3. Run the bot:

```
python bot.py
```

## Directory Structure

```
discord-notification-bot/
├── bot.py                # Main bot application logic
├── requirements.txt      # Python dependencies
├── Dockerfile            # Docker file for deploying to Railway
├── railway.json          # JSON for forcing Railway to use Docker instead of Nixpicks
└── .env                  # Environment file (create a .env file from this)
```

## Contributing

Feel free to open issues or submit pull requests for improvements or bug fixes.

## License

MIT License. See [LICENSE](LICENSE) for details.

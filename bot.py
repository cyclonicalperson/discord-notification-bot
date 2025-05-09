import discord
import asyncio
import requests
from bs4 import BeautifulSoup
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Fetch environment variables
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
ROLE_ID = os.getenv('ROLE_ID')

# Validate environment variables
if not TOKEN or not CHANNEL_ID or not ROLE_ID:
    logger.error("Missing required environment variables: DISCORD_TOKEN, CHANNEL_ID, or ROLE_ID")
    raise ValueError("Missing required environment variables!")

try:
    CHANNEL_ID = int(CHANNEL_ID)
    ROLE_ID = int(ROLE_ID)
except ValueError:
    logger.error("CHANNEL_ID and ROLE_ID must be valid integers")
    raise ValueError("CHANNEL_ID and ROLE_ID must be valid integers")

# Initialize intents and bot
intents = discord.Intents.default()
intents.message_content = True  # Required for commands
bot = commands.Bot(command_prefix='!', intents=intents)

# Set to store all seen announcement identifiers
seen_announcements = set()

# Record deployment time
DEPLOYMENT_TIME = datetime.now()
logger.info(f"Bot deployed at {DEPLOYMENT_TIME}")

async def check_announcements():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")
        return

    while not bot.is_closed():
        try:
            # Fetch the webpage
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get('https://imi.pmf.kg.ac.rs/oglasna-tabla', timeout=10, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract all announcement rows
            rows = soup.select('#oglasna_tabla_id tbody tr')
            if not rows:
                logger.warning("No announcement rows found on the webpage")
                await asyncio.sleep(300)
                continue

            # Process announcements
            new_announcements = []
            for row in rows:
                post_link_elem = row.select_one('.naslov_oglasa a')
                if not post_link_elem:
                    logger.warning("No post link element found in row")
                    continue
                post_link = post_link_elem.get('href', '')
                post_title = post_link_elem.text.strip()
                modal_id = post_link_elem.get('data-reveal-id', '')

                # Extract timestamp from the row (assuming second column)
                timestamp_elem = row.select_one('td:nth-child(2)')
                timestamp = timestamp_elem.text.strip() if timestamp_elem else "No timestamp"
                logger.info(f"Processing announcement: {post_title}, href: {post_link}, timestamp: {timestamp}")

                # Parse timestamp to datetime (assuming DD.MM.YYYY format)
                try:
                    if timestamp != "No timestamp":
                        announcement_time = datetime.strptime(timestamp, '%d.%m.%Y')
                        # Skip announcements older than deployment time
                        if announcement_time <= DEPLOYMENT_TIME:
                            logger.info(f"Skipping old announcement: {post_title} (timestamp: {timestamp})")
                            continue
                    else:
                        logger.warning(f"Skipping announcement with invalid timestamp: {post_title}")
                        continue
                except ValueError as e:
                    logger.error(f"Failed to parse timestamp '{timestamp}' for {post_title}: {e}")
                    continue

                # Extract summary from modal content if available
                modal = soup.select_one(f'#{modal_id}')
                summary_text = "No summary available."
                if modal:
                    summary_elem = modal.select_one('p:not(.lead):not(.news_title_date)')
                    if summary_elem:
                        summary_text = summary_elem.text.strip()[:200] + "..." if len(
                            summary_elem.text.strip()) > 200 else summary_elem.text.strip()

                # Use a fallback URL if post_link is invalid
                valid_url = "https://imi.pmf.kg.ac.rs/oglasna-tabla" if not post_link.startswith(
                    ('http://', 'https://')) else post_link
                logger.info(f"Using URL: {valid_url} for announcement: {post_title}")

                # Create a unique identifier using timestamp and URL
                unique_id = f"{timestamp}:{valid_url}"
                if unique_id not in seen_announcements:
                    new_announcements.append((post_title, valid_url, summary_text))
                    seen_announcements.add(unique_id)

            # Send notifications for new announcements in chronological order
            logger.info(f"Found {len(new_announcements)} new announcements to send")
            for title, link, summary in reversed(new_announcements):
                try:
                    logger.info(f"Attempting to send notification for: {title}")
                    embed = discord.Embed(
                        title=title,
                        description=summary,
                        url=link,
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="IMI PMF Kragujevac - Oglasna Tabla")
                    await channel.send(content=f"<@&{ROLE_ID}>", embed=embed)
                    logger.info(f"Successfully sent notification for post: {title} ({link})")
                    await asyncio.sleep(1)  # Prevent rate limiting
                except discord.errors.Forbidden as e:
                    logger.error(
                        f"Bot lacks permissions to send messages or mention role {ROLE_ID} in channel {CHANNEL_ID}: {e}")
                except discord.errors.HTTPException as e:
                    logger.error(f"Failed to send notification for {title}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error sending notification for {title}: {e}", exc_info=True)

            # Keep only the 50 most recent announcements to avoid memory growth
            if len(seen_announcements) > 50:
                seen_announcements.clear()
                for row in rows[:10]:
                    post_link_elem = row.select_one('.naslov_oglasa a')
                    if post_link_elem and post_link_elem.get('href'):
                        post_link = post_link_elem.get('href')
                        valid_url = post_link if post_link.startswith(
                            ('http://', 'https://')) else "https://imi.pmf.kg.ac.rs/oglasna-tabla"
                        timestamp_elem = row.select_one('td:nth-child(2)')
                        timestamp = timestamp_elem.text.strip() if timestamp_elem else "No timestamp"
                        # Only keep recent announcements
                        try:
                            if timestamp != "No timestamp":
                                announcement_time = datetime.strptime(timestamp, '%d.%m.%Y')
                                if announcement_time > DEPLOYMENT_TIME:
                                    unique_id = f"{timestamp}:{valid_url}"
                                    seen_announcements.add(unique_id)
                        except ValueError as e:
                            logger.error(f"Failed to parse timestamp '{timestamp}' during cleanup: {e}")

        except requests.RequestException as e:
            logger.error(f"Error fetching webpage: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in check_announcements: {e}", exc_info=True)

        await asyncio.sleep(300)  # Check every 5 minutes

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            await channel.send("Test message: The bot is online and working!")
            logger.info("Sent test message to channel")
        except discord.errors.Forbidden:
            logger.error(f"Bot lacks permissions to send messages in channel {CHANNEL_ID}")
    else:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")

    # Start checking announcements
    bot.loop.create_task(check_announcements())

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Unhandled error in {event}: {args}", exc_info=True)

@bot.command(name='check')
@commands.has_permissions(administrator=True)
async def manual_check(ctx):
    """Manually trigger an announcement check"""
    logger.info(f"Manual check triggered by {ctx.author}")
    await ctx.send("Checking for new announcements...")
    await check_announcements()
    await ctx.send("Check complete!")

@manual_check.error
async def manual_check_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    else:
        logger.error(f"Error in manual_check command: {error}")
        await ctx.send("An error occurred while checking announcements.")

# Run the bot
async def main():
    try:
        await bot.start(TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid bot token provided")
    except Exception as e:
        logger.error(f"Bot crashed with error: {e}", exc_info=True)
        await asyncio.sleep(5)
        await main()  # Retry after delay

if __name__ == "__main__":
    asyncio.run(main())
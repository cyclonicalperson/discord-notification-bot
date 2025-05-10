import discord
import asyncio
import requests
from bs4 import BeautifulSoup
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv
from urllib.parse import urljoin

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

async def scan_initial_announcements():
    """Scan all announcements on startup, add to seen_announcements, and send test messages without pings."""
    try:
        base_url = 'https://imi.pmf.kg.ac.rs/oglasna-tabla'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        total_rows = 0
        page_count = 0
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            logger.error(f"Channel with ID {CHANNEL_ID} not found during initial scan")
            return

        # Process all pages
        current_url = base_url
        while current_url:
            page_count += 1
            logger.info(f"Initial scan - Fetching page {page_count}: {current_url}")
            response = requests.get(current_url, timeout=10, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract all announcement rows
            rows = soup.select('#oglasna_tabla_id tbody tr')
            logger.info(f"Initial scan - Found {len(rows)} rows on page {page_count}")
            if not rows:
                logger.warning(f"No announcement rows found on page: {current_url}")
            else:
                total_rows += len(rows)
                for row in rows:
                    post_link_elem = row.select_one('.naslov_oglasa a')
                    if not post_link_elem:
                        logger.warning("No post link element found in row during initial scan")
                        continue
                    post_link = post_link_elem.get('href', '')
                    post_title = post_link_elem.text.strip()
                    modal_id = post_link_elem.get('data-reveal-id', '')

                    # Skip if no modal_id
                    if not modal_id:
                        logger.warning(f"No modal_id found for announcement: {post_title}, skipping")
                        continue

                    logger.info(f"Initial scan - Processing announcement: {post_title}, href: {post_link}, modal_id: {modal_id}")

                    # Extract summary from modal content if available
                    modal = soup.select_one(f'#{modal_id}')
                    summary_text = "No summary available."
                    if modal:
                        summary_elem = modal.select_one('p:not(.lead):not(.news_title_date)')
                        if summary_elem:
                            summary_text = summary_elem.text.strip()[:200] + "..." if len(
                                summary_elem.text.strip()) > 200 else summary_elem.text.strip()

                    # Use raw href as valid_url
                    valid_url = post_link
                    logger.info(f"Initial scan - Using URL: {valid_url} for announcement: {post_title}")

                    # Create a unique identifier using modal_id
                    unique_id = modal_id
                    seen_announcements.add(unique_id)

                    # Send test message for this announcement (without ping)
                    try:
                        logger.info(f"Initial scan - Sending test message for: {post_title}")
                        embed = discord.Embed(
                            title=post_title,
                            description=f"{summary_text}\n\nVisit https://imi.pmf.kg.ac.rs/oglasna-tabla for details.",
                            color=discord.Color.blue()
                        )
                        embed.set_footer(text="IMI PMF Kragujevac - Oglasna Tabla (Test Message)")
                        # Only set url if valid (http or https)
                        if valid_url.startswith(('http://', 'https://')):
                            embed.url = valid_url
                        else:
                            logger.info(f"Initial scan - Omitting URL for {post_title} due to invalid href: {valid_url}")
                        await channel.send(embed=embed)
                        logger.info(f"Initial scan - Successfully sent test message for: {post_title} (modal_id: {modal_id})")
                        await asyncio.sleep(1)  # Prevent rate limiting
                    except discord.errors.Forbidden as e:
                        logger.error(f"Bot lacks permissions to send test message in channel {CHANNEL_ID}: {e}")
                    except discord.errors.HTTPException as e:
                        logger.error(f"Failed to send test message for {post_title}: {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error sending test message for {post_title}: {e}", exc_info=True)

            # Check for next page
            next_link = soup.select_one('a.next, a[rel="next"], a.page-link, a[href*="page="], a[href*="/page/"]')
            if next_link and next_link.get('href'):
                current_url = urljoin(base_url, next_link['href'])
                logger.info(f"Initial scan - Found next page: {current_url}")
            else:
                current_url = None
                logger.info("Initial scan - No next page found, ending scan")

        logger.info(f"Initial scan complete. Found {total_rows} existing announcements across {page_count} pages.")

    except requests.RequestException as e:
        logger.error(f"Error fetching webpage during initial scan: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during initial scan: {e}", exc_info=True)

async def check_announcements():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")
        return

    while not bot.is_closed():
        try:
            base_url = 'https://imi.pmf.kg.ac.rs/oglasna-tabla'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            new_announcements = []
            total_rows = 0
            page_count = 0

            # Process all pages
            current_url = base_url
            while current_url:
                page_count += 1
                logger.info(f"Fetching page {page_count}: {current_url}")
                response = requests.get(current_url, timeout=10, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                # Extract all announcement rows
                rows = soup.select('#oglasna_tabla_id tbody tr')
                logger.info(f"Found {len(rows)} rows on page {page_count}")
                if not rows:
                    logger.warning(f"No announcement rows found on page: {current_url}")
                else:
                    total_rows += len(rows)
                    for row in rows:
                        post_link_elem = row.select_one('.naslov_oglasa a')
                        if not post_link_elem:
                            logger.warning("No post link element found in row")
                            continue
                        post_link = post_link_elem.get('href', '')
                        post_title = post_link_elem.text.strip()
                        modal_id = post_link_elem.get('data-reveal-id', '')

                        # Skip if no modal_id
                        if not modal_id:
                            logger.warning(f"No modal_id found for announcement: {post_title}, skipping")
                            continue

                        logger.info(f"Processing announcement: {post_title}, href: {post_link}, modal_id: {modal_id}")

                        # Extract summary from modal content if available
                        modal = soup.select_one(f'#{modal_id}')
                        summary_text = "No summary available."
                        if modal:
                            summary_elem = modal.select_one('p:not(.lead):not(.news_title_date)')
                            if summary_elem:
                                summary_text = summary_elem.text.strip()[:200] + "..." if len(
                                    summary_elem.text.strip()) > 200 else summary_elem.text.strip()

                        # Use raw href as valid_url
                        valid_url = post_link
                        logger.info(f"Using URL: {valid_url} for announcement: {post_title}")

                        # Create a unique identifier using modal_id
                        unique_id = modal_id
                        if unique_id not in seen_announcements:
                            new_announcements.append((post_title, valid_url, summary_text))
                            seen_announcements.add(unique_id)

                # Check for next page
                next_link = soup.select_one('a.next, a[rel="next"], a.page-link, a[href*="page="], a[href*="/page/"]')
                if next_link and next_link.get('href'):
                    current_url = urljoin(base_url, next_link['href'])
                    logger.info(f"Found next page: {current_url}")
                else:
                    current_url = None
                    logger.info("No next page found, ending check")

            # Send notifications for new announcements in chronological order
            logger.info(f"Found {len(new_announcements)} new announcements to send (processed {total_rows} total posts across {page_count} pages)")
            if not new_announcements and total_rows <= 20:
                logger.warning("No new announcements found and 20 or fewer posts processed. Possible pagination or JavaScript loading issue. Consider using selenium to render dynamic content.")
            for title, link, summary in reversed(new_announcements):
                try:
                    logger.info(f"Attempting to send notification for: {title}")
                    embed = discord.Embed(
                        title=title,
                        description=f"{summary}\n\nVisit https://imi.pmf.kg.ac.rs/oglasna-tabla for details.",
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="IMI PMF Kragujevac - Oglasna Tabla")
                    # Only set url if valid (http or https)
                    if link.startswith(('http://', 'https://')):
                        embed.url = link
                    else:
                        logger.info(f"Omitting URL for {title} due to invalid href: {link}")
                    await channel.send(content=f"<@&{ROLE_ID}>", embed=embed)
                    logger.info(f"Successfully sent notification for post: {title} (modal_id: {modal_id})")
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
                # Use the most recent rows from the last page processed
                for row in rows[:10]:
                    post_link_elem = row.select_one('.naslov_oglasa a')
                    if post_link_elem:
                        modal_id = post_link_elem.get('data-reveal-id', '')
                        if modal_id:
                            seen_announcements.add(modal_id)

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
            await channel.send("Test message: The bot is online and working! Starting initial scan of announcements...")
            logger.info("Sent test message to channel")
        except discord.errors.Forbidden:
            logger.error(f"Bot lacks permissions to send messages in channel {CHANNEL_ID}")
    else:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")

    # Perform initial scan of announcements
    await scan_initial_announcements()

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
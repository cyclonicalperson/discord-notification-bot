import os
import logging
import discord
import asyncio
import requests
import random
import re

import unicodedata
from discord.ext import commands
from bs4 import BeautifulSoup
from bs4 import NavigableString
from dotenv import load_dotenv
from urllib.parse import urljoin

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
ROLE_ID = int(os.getenv('ROLE_ID', '0'))

# Validate environment variables
if not (TOKEN and CHANNEL_ID and ROLE_ID):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set to store seen announcement modal IDs
seen_announcements = set()

# User-Agent rotation for cache-busting
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (X11; Linux x86_64) Safari/537.36'
]


def create_embed(title, url=None):
    """Create a Discord embed for an announcement."""
    embed = discord.Embed(
        title=title,
        description="Visit https://imi.pmf.kg.ac.rs/oglasna-tabla for details.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="IMI PMF Kragujevac - Oglasna Tabla")
    if url and url.startswith(('http://', 'https://')):
        embed.url = url
    return embed


async def fetch_announcements(base_url, add_to_seen=True, limit_newest=False):
    """Fetch announcements using requests."""
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'If-Modified-Since': '0'
    }
    announcements = []
    total_rows = 0
    page_count = 0
    current_url = base_url
    cycle_seen_ids = set()  # Track modal_ids in this fetch cycle to prevent duplicates

    while current_url:
        page_count += 1
        logger.info(f"Fetching page {page_count}: {current_url}")
        try:
            response = requests.get(current_url, timeout=10, headers=headers, allow_redirects=True)
            logger.info(f"Status: {response.status_code}, Final URL: {response.url}")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.select('#oglasna_tabla_id tbody tr, table tbody tr, .oglasna-tabla tbody tr')
            logger.info(f"Found {len(rows)} rows on page {page_count}")
            total_rows += len(rows)

            if not rows:
                logger.warning(f"No rows found on page {page_count}")
                logger.debug(f"Raw HTML (first 1000 chars): {soup.prettify()[:1000]}")
                break

            start_idx = 1 if limit_newest and page_count == 1 else 0
            if limit_newest and page_count == 1 and rows:
                logger.info(
                    f"Skipping first row: {rows[0].select_one('.naslov_oglasa a, td a').text.strip() if rows[0].select_one('.naslov_oglasa a, td a') else 'None'}")

            for row in rows[start_idx:]:
                post_link_elem = row.select_one('.naslov_oglasa a, td a')
                if not post_link_elem:
                    logger.warning("No post link element found in row")
                    continue
                post_link = post_link_elem.get('href', '')
                post_title = post_link_elem.text.strip()
                modal_id = post_link_elem.get('data-reveal-id', post_title)

                if not modal_id:
                    logger.warning(f"No modal_id found for announcement: {post_title}")
                    continue

                # Skip if modal_id was already processed in this cycle
                if modal_id in cycle_seen_ids:
                    logger.debug(f"Skipping duplicate modal_id in cycle: {modal_id} for {post_title}")
                    continue

                # Skip if already seen globally and not adding to seen
                if not add_to_seen and modal_id in seen_announcements:
                    continue

                modal = soup.select_one(f'#{modal_id}')
                summary_text = "No summary available."
                if modal:
                    # Get all text content from the modal, excluding title and date elements
                    summary_elems = modal.select('p:not(.lead):not(.news_title_date)')
                    logger.debug(f"Found {len(summary_elems)} <p> elements for modal_id: {modal_id}")
                    if summary_elems:
                        logger.debug(f"Modal HTML for {post_title}: {modal.prettify()[:1000]}")
                    seen_texts = set()
                    unique_texts = []
                    for p in summary_elems:
                        # Work on a copy to preserve original structure
                        p_copy = p.__copy__()
                        # Check for existing markdown links [text](url)
                        raw_text = p_copy.get_text(strip=False)
                        markdown_link_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
                        existing_markdown_links = re.findall(markdown_link_pattern, raw_text)
                        for i, (link_text, link_url) in enumerate(existing_markdown_links):
                            placeholder = f"__MD_LINK_{i}__"
                            raw_text = raw_text.replace(f"[{link_text}]({link_url})", placeholder)
                            p_copy = BeautifulSoup(raw_text, 'html.parser')
                        # Process <a> tags for links
                        for a in p_copy.find_all('a'):
                            link_text = a.get_text(strip=False).strip()
                            link_url = urljoin(base_url, a.get('href', ''))
                            a.replace_with(NavigableString(f"[{link_text}]({link_url})"))
                        # Process <strong> and <b> tags for bold
                        for bold in p_copy.find_all(['strong', 'b']):
                            bold_text = bold.get_text(strip=False).strip()
                            bold.replace_with(NavigableString(f"**{bold_text}**"))
                        # Restore existing markdown links
                        raw_text = p_copy.get_text(strip=False).strip()
                        for i, (link_text, link_url) in enumerate(existing_markdown_links):
                            raw_text = raw_text.replace(f"__MD_LINK_{i}__", f"[{link_text}]({link_url})")
                        # Normalize for comparison: aggressive Unicode normalization and cleanup
                        normalized_text = unicodedata.normalize('NFKD', raw_text)  # Normalize Unicode
                        normalized_text = re.sub(r'[^\w\s]', '', normalized_text)  # Remove non-word chars
                        normalized_text = re.sub(r'\s+', ' ', normalized_text).strip().lower()  # Collapse spaces
                        logger.debug(f"Raw text for {post_title}: {raw_text[:100]}")
                        logger.debug(f"Normalized text for {post_title}: {normalized_text[:100]}")
                        if normalized_text and normalized_text not in seen_texts:
                            seen_texts.add(normalized_text)
                            unique_texts.append(raw_text)
                        elif normalized_text:
                            logger.debug(f"Duplicate text found in {post_title}: {normalized_text[:100]}")
                    summary_text = '\n\n'.join(unique_texts) if unique_texts else "No summary available."

                unique_id = modal_id
                cycle_seen_ids.add(unique_id)  # Mark as seen in this cycle
                if add_to_seen:
                    seen_announcements.add(unique_id)
                    logger.info(f"Added to seen: {post_title} (modal_id: {unique_id})")
                elif unique_id not in seen_announcements:
                    announcements.append((post_title, post_link, summary_text, unique_id))
                    logger.info(f"Added to new announcements: {post_title} (modal_id: {unique_id})")

            next_link = soup.select_one('a.next, a[rel="next"], a.page-link, a[href*="page="], a[href*="/page/"]')
            current_url = urljoin(base_url, next_link['href']) if next_link and next_link.get('href') else None

        except requests.RequestException as e:
            logger.error(f"Error fetching page {current_url}: {e}")
            break

    logger.info(f"Processed {total_rows} announcements across {page_count} pages")
    return announcements, total_rows


async def scan_initial_announcements():
    """Scan existing announcements on startup without notifying."""
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            seen_announcements.clear()  # Clear to avoid stale data
            logger.info(f"Before scan: seen_announcements size = {len(seen_announcements)}")
            _, total_rows = await fetch_announcements('https://imi.pmf.kg.ac.rs/oglasna-tabla', add_to_seen=True,
                                                      limit_newest=False)
            logger.info(f"After scan: seen_announcements size = {len(seen_announcements)}")
            if total_rows <= 20:
                logger.warning("Few announcements processed. Possible issue with URL or table selector.")
                await channel.send(
                    "Warning: Bot found 0 announcements. Possible wrong URL or table selector. Check logs.")
        except Exception as e:
            logger.error(f"Error in scan_initial_announcements: {e}")
            await channel.send("Error: Bot failed to scan announcements. Check logs.")
    else:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")


async def check_announcements():
    """Periodically check for new announcements and notify."""
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")
        return

    # Wait for initial scan to complete
    await asyncio.sleep(5)

    while not bot.is_closed():
        try:
            logger.info(f"Before check: seen_announcements size = {len(seen_announcements)}")
            new_announcements, total_rows = await fetch_announcements(
                'https://imi.pmf.kg.ac.rs/oglasna-tabla', add_to_seen=False
            )
            logger.info(f"Found {len(new_announcements)} new announcements")

            for title, link, summary, modal_id in reversed(new_announcements):
                seen_announcements.add(modal_id)
                logger.info(f"New announcement: {title} (modal_id: {modal_id})")
                try:
                    # Create embed with hardcoded description
                    embed = create_embed(title, link)

                    # Send message with role mention, title, and summary in content only
                    message_content = f"<@&{ROLE_ID}> **{title}**"
                    if summary and summary.strip() and summary != "No summary available.":
                        message_content += f"\n\n{summary}"

                    await channel.send(content=message_content, embed=embed)
                    logger.info(f"Sent notification for: {title} (modal_id: {modal_id})")
                    await asyncio.sleep(1)
                except discord.errors.Forbidden:
                    logger.error(f"Bot lacks permissions to send messages in channel {CHANNEL_ID}")
                except discord.errors.HTTPException as e:
                    logger.error(f"Failed to send notification for {title}: {e}")

            if len(seen_announcements) > 50:
                seen_announcements.clear()
                _, _ = await fetch_announcements(
                    'https://imi.pmf.kg.ac.rs/oglasna-tabla', add_to_seen=True, limit_newest=False
                )

        except Exception as e:
            logger.error(f"Error in check_announcements: {e}")

        await asyncio.sleep(300)


@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            await channel.send("Test message: The bot is online and working!")
            logger.info("Sent test message")
        except discord.errors.Forbidden:
            logger.error(f"Bot lacks permissions to send messages in channel {CHANNEL_ID}")
    else:
        logger.error(f"Channel with ID {CHANNEL_ID} not found")

    await scan_initial_announcements()
    # Start periodic checks after initial scan
    bot.loop.create_task(check_announcements())


@bot.command(name='check')
@commands.has_permissions(administrator=True)
async def manual_check(ctx):
    """Manually trigger an announcement check."""
    logger.info(f"Manual check triggered by {ctx.author}")
    await ctx.send("Checking for new announcements...")
    await check_announcements()
    await ctx.send("Check complete!")


@manual_check.error
async def manual_check_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    else:
        logger.error(f"Error in manual_check: {error}")
        await ctx.send("An error occurred while checking announcements.")


@bot.command(name='debug_reread')
@commands.has_permissions(administrator=True)
async def debug_reread(ctx):
    """Temporarily re-read the last announcement for testing."""
    logger.info(f"Debug reread triggered by {ctx.author}")
    if seen_announcements:
        # Remove the most recent modal_id to reprocess it
        seen_announcements.pop()
        logger.info("Removed last seen announcement for reprocessing")
    await ctx.send("Re-reading the last announcement...")
    await check_announcements()
    await ctx.send("Reread complete!")


@debug_reread.error
async def debug_reread_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.")
    else:
        logger.error(f"Error in debug_reread: {error}")
        await ctx.send("An error occurred while re-reading the announcement.")


async def main():
    try:
        await bot.start(TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid bot token")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        await asyncio.sleep(5)
        await main()


if __name__ == "__main__":
    asyncio.run(main())

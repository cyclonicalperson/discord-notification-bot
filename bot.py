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
from urllib.parse import urljoin, quote, urlparse

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


def fix_url(url, base_url):
    """Fix and properly encode URLs."""
    if not url:
        return ""

    # If it's already a complete URL, validate and return
    if url.startswith(('http://', 'https://')):
        return url

    # Join with base URL
    full_url = urljoin(base_url, url)

    # Parse URL to handle encoding properly
    parsed = urlparse(full_url)

    # Only encode the path part, leave the rest intact
    if parsed.path:
        # Encode only non-ASCII characters and spaces, preserve slashes and other URL-safe chars
        encoded_path = quote(parsed.path.encode('utf-8'), safe='/:@!$&\'()*+,;=')
        full_url = f"{parsed.scheme}://{parsed.netloc}{encoded_path}"
        if parsed.query:
            full_url += f"?{parsed.query}"
        if parsed.fragment:
            full_url += f"#{parsed.fragment}"

    return full_url


def transliterate_serbian(text):
    """Transliterate Serbian Cyrillic and Latin diacritics to basic Latin for normalization."""
    mapping = {
        # Cyrillic
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'ђ': 'dj', 'е': 'e', 'ж': 'z', 'з': 'z', 'и': 'i',
        'ј': 'j', 'к': 'k', 'л': 'l', 'љ': 'lj', 'м': 'm', 'н': 'n', 'њ': 'nj', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'ћ': 'c', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'c', 'џ': 'dz', 'ш': 's',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Ђ': 'Dj', 'Е': 'E', 'Ж': 'Z', 'З': 'Z', 'И': 'I',
        'Ј': 'J', 'К': 'K', 'Л': 'L', 'Љ': 'Lj', 'М': 'M', 'Н': 'N', 'Њ': 'Nj', 'О': 'O', 'П': 'P', 'Р': 'R',
        'С': 'S', 'Т': 'T', 'Ћ': 'C', 'У': 'U', 'Ф': 'F', 'Х': 'H', 'Ц': 'C', 'Ч': 'C', 'Џ': 'Dz', 'Ш': 'S',
        # Latin diacritics
        'č': 'c', 'ć': 'c', 'đ': 'dj', 'š': 's', 'ž': 'z',
        'Č': 'C', 'Ć': 'C', 'Đ': 'Dj', 'Š': 'S', 'Ž': 'Z',
    }
    return ''.join(mapping.get(c, c) for c in text)


def normalize_whitespace_and_clean(text):
    """Normalize whitespace while preserving intentional formatting."""
    if not text or not text.strip():
        return ""

    # Replace problematic Unicode whitespace with regular spaces, but preserve newlines
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        # Replace Unicode whitespace characters with regular spaces, but keep structure
        line = ''.join(' ' if unicodedata.category(c).startswith('Z') and c != '\n' else c for c in line)
        # Only collapse multiple spaces within a line, don't strip leading/trailing spaces completely
        line = re.sub(r' {2,}', ' ', line)  # Replace 2+ spaces with single space
        cleaned_lines.append(line)

    # Join lines back and clean up excessive newlines (more than 2 consecutive)
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)  # Max 2 consecutive newlines

    return result.strip()  # Only strip from very beginning and end


def create_dedup_key(text):
    """Create a consistent deduplication key from text without destroying original formatting."""
    if not text:
        return ""

    # Create a normalized version ONLY for deduplication, don't use for display
    # Convert to lowercase and transliterate
    translit = transliterate_serbian(text.lower())

    # Remove all punctuation, whitespace, and formatting for comparison
    clean_key = re.sub(r'\W', '', translit)  # Remove everything except word characters

    # Further normalize common patterns in Serbian academic announcements
    clean_key = re.sub(r'(daje|ostatak|broj|indeksa|ucionici|ucionnica|kolokvijum|poceti)', '', clean_key)
    clean_key = re.sub(r'\d+', 'N', clean_key)  # Replace all numbers with 'N' for pattern matching

    return clean_key


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

                # Get the link and fix it properly
                raw_link = post_link_elem.get('href', '')
                post_link = fix_url(raw_link, base_url)
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
                    # Get all content from the modal - be more inclusive with selectors
                    # Look for paragraphs, divs, lists, and any text content
                    summary_elems = modal.select(
                        'p:not(.lead):not(.news_title_date), div:not(.modal-header):not(.close-reveal-modal):not(.share-links), ul, ol, li')

                    # If no structured elements found, get any direct text content from the modal
                    if not summary_elems:
                        # Look for any text content in the modal
                        modal_text = modal.get_text().strip()
                        if modal_text:
                            # Split by lines and process as individual elements
                            lines = [line.strip() for line in modal_text.split('\n') if line.strip()]
                            # Filter out title/header lines and common elements like "Podeli"
                            content_lines = []
                            for line in lines:
                                # Skip very short lines, titles/headers, share links, and common UI elements
                                if (len(line) > 20 and
                                        not line.endswith(':') and
                                        '©' not in line and
                                        'podeli' not in line.lower() and
                                        'share' not in line.lower() and
                                        'facebook' not in line.lower() and
                                        'twitter' not in line.lower() and
                                        not line.startswith('×')):
                                    content_lines.append(line)
                            if content_lines:
                                summary_text = '\n\n'.join(content_lines)
                            else:
                                summary_text = "No summary available."
                        else:
                            summary_text = "No summary available."
                    else:
                        logger.debug(f"Found {len(summary_elems)} content elements for modal_id: {modal_id}")

                        if summary_elems:
                            logger.debug(f"Modal HTML for {post_title}: {modal.prettify()[:1000]}")

                        # Use a more robust deduplication approach with semantic similarity checking
                        seen_keys = set()
                        seen_semantic_keys = set()  # For checking semantic similarity
                        unique_texts = []

                        for elem in summary_elems:
                            # Skip nested list items to avoid duplication
                            if elem.name == 'li' and elem.find_parent(['ul', 'ol']) in summary_elems:
                                continue

                            # Skip elements that contain share/social media links
                            elem_text = elem.get_text().lower()
                            if ('podeli' in elem_text or 'share' in elem_text or
                                    'facebook' in elem_text or 'twitter' in elem_text or
                                    elem_text.strip().startswith('×')):
                                continue

                            # Work on a copy to preserve original structure
                            elem_copy = elem.__copy__()

                            # Process <a> tags for links, but skip social/share links
                            for a in elem_copy.find_all('a'):
                                link_text = a.get_text(strip=True).strip().lower()
                                link_href = a.get('href', '').lower()

                                # Skip share/social media links
                                if ('podeli' in link_text or 'share' in link_text or
                                        'facebook' in link_text or 'twitter' in link_text or
                                        'facebook' in link_href or 'twitter' in link_href or
                                        'instagram' in link_href or 'linkedin' in link_href):
                                    a.extract()  # Remove share links entirely
                                    continue

                                if link_text:  # Only process non-empty, non-share links
                                    # Use the new fix_url function for proper URL handling
                                    original_href = a.get('href', '')
                                    fixed_link_url = fix_url(original_href, base_url)
                                    a.replace_with(NavigableString(f"[{a.get_text(strip=True)}]({fixed_link_url})"))
                                else:
                                    a.extract()  # Remove empty links

                            # Process <strong> and <b> tags for bold
                            for bold in elem_copy.find_all(['strong', 'b']):
                                bold_text = bold.get_text(strip=True).strip()
                                if bold_text:  # Only process non-empty bold text
                                    bold.replace_with(NavigableString(f"**{bold_text}**"))
                                else:
                                    bold.extract()  # Remove empty bold tags

                            # Handle lists specially to format them properly
                            if elem.name in ['ul', 'ol']:
                                list_items = elem_copy.find_all('li')
                                if list_items:
                                    formatted_items = []
                                    for li in list_items:
                                        li_text = li.get_text()
                                        # Skip list items that are share links
                                        if 'podeli' in li_text.lower() or 'share' in li_text.lower():
                                            continue
                                        # Only do minimal cleaning on list items
                                        li_text = normalize_whitespace_and_clean(li_text)
                                        if li_text:
                                            formatted_items.append(f"- {li_text}")

                                    if formatted_items:
                                        clean_text = '\n'.join(formatted_items)
                                    else:
                                        continue
                                else:
                                    continue
                            else:
                                # Get the processed text for paragraphs and preserve original formatting
                                raw_text = elem_copy.get_text()
                                # Apply minimal normalization to preserve original spacing
                                clean_text = normalize_whitespace_and_clean(raw_text)

                            # Skip empty content
                            if not clean_text:
                                continue

                            # Create deduplication key (this is only for comparison, not for display)
                            dedup_key = create_dedup_key(clean_text)

                            # Also create a semantic key for more aggressive deduplication
                            semantic_key = re.sub(r'\W+', '', dedup_key)  # Remove remaining non-word characters

                            # Log for debugging
                            logger.debug(f"Original text: {clean_text[:100]}")
                            logger.debug(f"Dedup key: {dedup_key[:100]}")
                            logger.debug(f"Semantic key: {semantic_key[:50]}")

                            # Check for both exact and semantic duplicates
                            is_duplicate = False
                            if dedup_key in seen_keys:
                                is_duplicate = True
                                logger.debug(f"Exact duplicate found: {dedup_key[:30]}")
                            elif semantic_key in seen_semantic_keys and len(
                                    semantic_key) > 15:  # Only for substantial content
                                is_duplicate = True
                                logger.debug(f"Semantic duplicate found: {semantic_key[:30]}")

                            # Check for substring relationships (one text contains another) - more lenient threshold
                            if not is_duplicate and len(semantic_key) > 10:
                                for existing_key in seen_semantic_keys:
                                    if (len(existing_key) > 10 and
                                            (len(semantic_key) > 20 and semantic_key in existing_key) or
                                            (len(existing_key) > 20 and existing_key in semantic_key)):
                                        is_duplicate = True
                                        logger.debug(
                                            f"Substring duplicate found: {semantic_key[:30]} vs {existing_key[:30]}")
                                        break

                            if not is_duplicate and dedup_key and semantic_key:
                                seen_keys.add(dedup_key)
                                seen_semantic_keys.add(semantic_key)
                                unique_texts.append(clean_text)  # Use original formatting for display
                            elif is_duplicate:
                                logger.debug(f"Duplicate content skipped for {post_title}")

                        # Join unique texts with double newlines, preserving original formatting
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
                    "Warning: Bot found few announcements. Possible wrong URL or table selector. Check logs.")
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
                    # Create embed with the properly fixed link
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

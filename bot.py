import discord
import asyncio
import requests
from bs4 import BeautifulSoup
import os

# Fetching environment variables (correctly)
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')  # This will be a string in Railway
ROLE_ID = os.getenv('ROLE_ID')

# Debugging: Print out the environment variables to check them
print(f"DISCORD_TOKEN: {TOKEN}")
print(f"CHANNEL_ID: {CHANNEL_ID}")
print(f"ROLE_ID: {ROLE_ID}")

# Validate that these variables are not None
if not TOKEN or not CHANNEL_ID or not ROLE_ID:
    raise ValueError("Missing required environment variables!")

# Convert CHANNEL_ID and ROLE_ID to integers
CHANNEL_ID = int(CHANNEL_ID)
ROLE_ID = int(ROLE_ID)

# Initialize intents and bot client
intents = discord.Intents.default()
client = discord.Client(intents=intents)

last_seen_post = None

async def check_announcements():
    global last_seen_post
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while not client.is_closed():
        try:
            response = requests.get('https://imi.pmf.kg.ac.rs/oglasna-tabla', timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            posts = soup.select('.entry-title a')
            summaries = soup.select('.td-excerpt')

            if posts:
                latest_post = posts[0]
                post_title = latest_post.text.strip()
                post_link = latest_post['href']
                summary_text = summaries[0].text.strip() if summaries else "No summary available."

                if last_seen_post != post_link:
                    last_seen_post = post_link

                    embed = discord.Embed(
                        title=post_title,
                        description=summary_text,
                        url=post_link,
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="IMI PMF Kragujevac - Oglasna Tabla")

                    await channel.send(content=f"<@&{ROLE_ID}>", embed=embed)

        except Exception as e:
            print(f"Error fetching posts: {e}")

        await asyncio.sleep(300)  # 5 minutes


@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    client.loop.create_task(check_announcements())


def run_bot():
    try:
        client.run(TOKEN)
    except Exception as e:
        print(f'Bot crashed with error: {e}. Restarting...')
        asyncio.sleep(5)
        run_bot()


if __name__ == "__main__":
    run_bot()

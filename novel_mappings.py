"""
novel_mappings.py

Mapping file for your own novel feed.
For each hosting site, we store:
  - translator: your username on that site.
  - host_logo: the URL for the site's logo.
  - coin_emoji: optional emoji for coin display in paid feed
  - novels: a dictionary mapping novel titles to their details:
      - discord_role_id: the Discord role ID for the novel.
      - novel_url: canonical/series URL.
      - featured_image: cover URL.
      - pub_date_override: optional dict for forcing hh:mm:ss in output. only affects paid chapters.
      - custom_description: (optional) override for <description> in free feed.

Also included are helper getters at the bottom.
"""

HOSTING_SITE_DATA = {
    "Mistmint Haven": {
        "feed_url": "https://www.mistminthaven.com/feed/",
        "comments_feed_url": "https://api.mistminthaven.com/api/comments/trans/all-comments",
        "translator": "CannibalTurtle",
        "host_logo": "https://www.mistminthaven.com/images/mascot_mistmint.png",
        "coin_emoji": "<:mistmint_currency:1433046707121422487>",
        "token_secret": "MISTMINT_COOKIE",
        "novels": {
            "[Quick Transmigration] The Delicate Little Beauty Keeps Getting Caught": {
                "novelupdates_feed_url": "https://www.novelupdates.com/series/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught/feed/",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught/chapters",
                "discord_role_id": "<@&1431675643078250646>",
                "novel_url": "https://www.mistminthaven.com/novels/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught",
                "featured_image": "https://i.imgur.com/vqvVVz9.png",
                "novel_id": "8ebd3484-d5b2-422d-a22d-11404bc8481f", #comment homepage for scraping reply chain
                # for manually updated paid feed
                "short_code": "tdlbkgc", #for parsing feed without guid. Also for short_code.

                # ─── webhook-only fields ───
                "chapter_count": "734 chapters + 3 extras",
                "last_chapter": "Extra 3",
                "start_date": "1/11/2025",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:468087cutebunny:1431678613002125313>",
                "extra_ping_roles": "<@&1329500516304158901> <@&1329427832077684736> <@&1330469077784727562>",
                "discord_role_url": "https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "history_file": "tdlbkgc_history.json",
                "custom_description": """【Delicate, soft, pretty little shou × paranoid, psychotic villain gong】
Dark room, forced confinement, obsessive pampering.
Shen Yu is bound to a system. His task is to enter various mission worlds and stop anomalous data from causing the worlds' collapse.
He’s been completing the missions beautifully, except… the process seems a bit off—
A mentally unstable financial magnate, eyes blood-red, holds him by the waist on the bed and murmurs hoarsely: “Don’t go.”
A top award-winning actor bends close, lowering his head to drop a kiss by his ear: “You really are beautiful like this.”
The sound of metal chains clatters—
The chieftain of a beautiful sea-serpent race coils around his trembling, tearful body…
It’s 1v1. Sweet, sweet, sweet."""
            },
            "Quick Transmigration: The Villain Is Too Pampered and Alluring": {
                "novelupdates_feed_url": "https://www.novelupdates.com/series/quick-transmigration-the-villain-is-too-pampered-and-alluring/feed/",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/quick-transmigration-the-villain-is-too-pampered-and-alluring/chapters",
                "discord_role_id": "<@&1329391480435114005>",
                "novel_url": "https://www.mistminthaven.com/novels/quick-transmigration-the-villain-is-too-pampered-and-alluring",
                "featured_image": "https://i.imgur.com/5sxtfVf.jpeg",
                "novel_id": "24f3efce-5b52-4dfe-a90e-14bcfb3f56c6", #comment homepage for scraping reply chain
                "short_code": "tvitpa", #for parsing feed without guid. Also for short_code.

                # ─── webhook-only fields ───
                "chapter_count": "1184 chapters + 8 extras",
                "last_chapter": "Extra 8",
                "start_date": "31/8/2024",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:468087cutebunny:1431678613002125313>",
                "extra_ping_roles": "<@&1329500516304158901> <@&1329427832077684736> <@&1330469014895595620>",
                "discord_role_url": "https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "history_file": "tvitpa_history.json",
                "custom_description": """To survive, Sheng Nuan must traverse different worlds, playing the role of self-destructive cannon fodder while saving the darkest villains. These villains are cold-blooded, obsessive, and ruthless—capable of annihilating millions with a smile and destroying the world with a wave of their hand. Holding the cannon fodder’s script, Sheng Nuan is terrified…
Later:
A paranoid young man with a gloomy expression: “Nuan Nuan, you’re not allowed to go anywhere except by my side…”
The cold-blooded emperor whose face was stained with blood: “Nuan Nuan, for you, what does it matter if the empire falls?”
The demonized immortal with snow-white hair: “Nuan Nuan, you are my inner demon.”
The zombie king of the apocalypse with an unwavering gaze: “Nuan Nuan, it’s your choice—kill me, or save me.”
Sheng Nuan became even more panicked…"""
        },
     },
  },
}

# ---------------- Utility Functions ----------------

def get_host_translator(host):
    """Returns the translator name for the given hosting site."""
    return HOSTING_SITE_DATA.get(host, {}).get("translator", "")

def get_host_logo(host):
    """Returns the hosting site's logo URL for the given host."""
    return HOSTING_SITE_DATA.get(host, {}).get("host_logo", "")

def get_novel_details(host, novel_title):
    """Returns the details of a novel (as a dict) from the specified hosting site."""
    return HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})

def get_novel_discord_role(novel_title, host):
    """
    Returns the Discord role ID for the given novel.
    If the novel title appears in the NSFW list (via get_nsfw_novels()),
    appends the extra role.
    """
    details = get_novel_details(host, novel_title)
    base_role = details.get("discord_role_id", "")
    if novel_title in get_nsfw_novels():
        base_role += " | <@&1343352825811439616>"
    return base_role

def get_novel_url(novel_title, host):
    """Returns the URL for the given novel on the specified hosting site."""
    details = get_novel_details(host, novel_title)
    return details.get("novel_url", "")

def get_featured_image(novel_title, host):
    """Returns the featured image URL for the given novel on the specified hosting site."""
    details = get_novel_details(host, novel_title)
    return details.get("featured_image", "")

def get_nsfw_novels():
    """Returns the list of NSFW novel titles."""
    return [
        # e.g. "Some NSFW Novel Title"
    ]

def get_coin_emoji(host):
    """Emoji string used in <coin> for paid feed."""
    return HOSTING_SITE_DATA.get(host, {}).get("coin_emoji", "")

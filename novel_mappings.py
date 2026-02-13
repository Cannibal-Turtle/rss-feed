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
            "Help! I Accidentally Flirted with the Lord God, What Do I Do?!": {
                "novelupdates_feed_url": "",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/help-i-accidentally-flirted-with-the-lord-god-what-do-i-do/chapters",
                "discord_role_id": "<@&1471460385348386847>",
                "novel_url": "https://www.mistminthaven.com/novels/help-i-accidentally-flirted-with-the-lord-god-what-do-i-do",
                "featured_image": "https://i.imgur.com/7LRK6Uw.png",
                "novel_id": "5868afe3-4a39-43ed-ae1c-314a8b3ffebe",
                "short_code": "hiaflg",

                # ─── webhook-only fields ───
                "chapter_count": "503 Chapters",
                "last_chapter": "Chapter 503",
                "start_date": "13/2/2026",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:piggy_warrior:1471462818489307283>",
                "extra_ping_roles": "<@&1329500516304158901> <@&1329427832077684736> <@&1330469306936328286> <@&1330469077784727562>",
                "discord_role_url": "https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "history_file": "hiaflg_history.json",
                "custom_description": """【Quick Transmigration + Double Male Leads + Cannon Fodder Counterattack + Main Shou + 1v1 + Double Clean】
The Lord God got scammed in an online relationship!
The other party even ran off on the way to meet in person!
Enraged, the Lord God issued a special-class wanted order, determined to drag back the wife who suddenly disappeared on him.
......
Xie Yaochen, who has already hidden himself inside a small world to carry out missions, blinks innocently.
“Dating? Never done that.”
“Online dating scam? No idea.”
“Special-class wanted criminal? Don’t know him either.”
Bound to a cannon fodder counterattack system, he happily travels through various small worlds. While cleaning up idiots, he even starts a sweet romance on the side.
His boyfriend is tall and handsome and loves him so much. If certain parts of him didn’t keep making him see that damn dog Lord God, it would be perfect...
Damn dog:
^_^"""
            },
            "Whose Simping Male Supporting Character Is Being Held and Kissed by the Male Lead?": {
                "novelupdates_feed_url": "https://www.novelupdates.com/series/whose-simping-male-supporting-character-is-being-held-and-kissed-by-the-male-lead/feed/",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/whose-simping-male-supporting-character-is-being-held-and-kissed-by-the-male-lead/chapters",
                "discord_role_id": "<@&1462773952144478334>",
                "novel_url": "https://www.mistminthaven.com/novels/whose-simping-male-supporting-character-is-being-held-and-kissed-by-the-male-lead",
                "featured_image": "https://i.imgur.com/zea8LXV.png",
                "novel_id": "4ee66cf7-3d4f-4cd1-b958-8a2dac6e167b",
                "short_code": "wsmsc",

                # ─── webhook-only fields ───
                "chapter_count": "160 chapters + 3 extras",
                "last_chapter": "Afterword 2",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:neko_simp:1462777063705546763>",
                "extra_ping_roles": "<@&1329500516304158901> <@&1437070731308699842> <@&1330469400553197588> <@&1330469077784727562>",
                "discord_role_url": "https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "custom_description": """【Universal-darling shou, bittersweet tone, sour first then sweet, livestream variety show, shura-field free-for-all, double male leads, double purity, HE】
Wen Yanyu, a cannon-fodder supporting male universally hated online for obsessively clinging to the male lead and dragging himself into public controversy, suddenly awakens self-awareness and gets bound to a system, sent off to take missions.
After countless cycles that grind him down in both body and mind, Wen Yanyu returns in a body shattered by missions. He decides to give up trying, planning to muddle through the variety show the company lined up for him and earn a bit of retirement money.
Who would have thought that on what should have been a show meant to turn him into a laughingstock, the other guests’ gazes start getting stranger and stranger. Odd physical contact. Unexplained shura-fields.
Netizens who once angrily cursed him begin piecing things together from every tiny detail. His almost self-punishing behavior. His complete disregard for his own life. The doctor’s on-show medical pronouncement of impending death. And finally, the scar that nearly severed him at the waist. They all fell silent.
“Wuwu, how much has my wife suffered? I’ve caught a disease where I cry the moment I see my wife!”
“Wife, don’t like Fu Hanchuan anymore, okay? Be with us instead.”
——
The once ice-cold male lead who despised him to the extreme abandons his work, chases the variety show, follows him wherever he goes, blocks every rival, and because of one of his fevers, is so frightened that he breaks down crying in front of everyone.
Holding him in his arms, kissing him while coaxing him, his voice trembling with fear: “Good baby will live to a hundred years old, happy and safe.”
Netizens: redefining ‘hate to the extreme’. Fu Hanchuan! You brat, keep your hands off my bunny baby!"""
            },
            "After Transmigrating into the Villain, I Got a HE with the Female Lead's Older Brother": {
                "novelupdates_feed_url": "https://www.novelupdates.com/series/after-transmigrating-into-the-villain-i-got-a-he-with-the-female-leads-older-brother/feed/",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/after-transmigrating-into-the-villain-i-got-a-he-with-the-female-lead-s-older-brother/chapters",
                "discord_role_id": "<@&1437846306625290260>",
                "novel_url": "https://www.mistminthaven.com/novels/after-transmigrating-into-the-villain-i-got-a-he-with-the-female-lead-s-older-brother",
                "featured_image": "https://i.imgur.com/lGogTew.png",
                "novel_id": "8ae77ae4-8871-4ac3-8bc4-2a094f825ea0", #comment homepage for scraping reply chain
                "short_code": "atvhe",

                # ─── webhook-only fields ───
                "chapter_count": "130 chapters",
                "last_chapter": "Chapter 130",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:hashigarakiheartlove:1437849521991454830>",
                "extra_ping_roles": "<@&1329500516304158901> <@&1437070570582708345> <@&1330469077784727562>",
                "discord_role_url": "https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "custom_description": """Calm, domineering CEO gong vs transmigrated clever shou【transmigration + 1v1 + double clean + sweet pampering】
Song Wan fell gravely ill. Rescue efforts failed, and he died.
When he opened his eyes again, he transmigrated into an abusive, dog-blood romance novel, becoming the villain who shared his exact name, the one who kept sabotaging the male and female leads’ romance.
To prevent the novel villain’s tragic ending from landing on his own head, Song Wan decided to turn over a new leaf.
Just like the system Siri said, the original host had committed too many evil deeds, which was why his ending was so miserable. As long as he did not block the male and female leads from falling in love and did not target the male lead, then it would be fine—
Fine my ass!
Other people transmigrated into the beginning or the middle of the story. He was practically about to transmigrate straight into the grand finale!
The original owner had done every bad thing imaginable and had even drugged the male lead, intending to destroy the male lead’s chastity.
This was bad! Song Wan’s vision went black. He took off in a hundred-meter sprint. Even if he had to kick the door down, he had to rescue the male lead from the hotel room laced with aphrodisiacs.
But the moment the door opened and Song Wan crashed headfirst into the sofa, he froze.
What was going on?
The one who had been drugged in the room was not the male lead at all. How was it the female lead’s brother instead!!!"""
            },
            "[Quick Transmigration] The Delicate Little Beauty Keeps Getting Caught": {
                "novelupdates_feed_url": "https://www.novelupdates.com/series/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught/feed/",
                "paid_feed_url": "https://api.mistminthaven.com/api/novels/slug/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught/chapters",
                "discord_role_id": "<@&1431675643078250646>",
                "novel_url": "https://www.mistminthaven.com/novels/quick-transmigration-the-delicate-little-beauty-keeps-getting-caught",
                "featured_image": "https://i.imgur.com/vqvVVz9.png",
                "novel_id": "8ebd3484-d5b2-422d-a22d-11404bc8481f", #comment homepage for scraping reply chain
                "short_code": "tdlbkgc",

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
                "short_code": "tvitpa",

                # ─── webhook-only fields ───
                "chapter_count": "1184 chapters + 8 extras",
                "last_chapter": "Extra 8",
                "start_date": "31/8/2024",
                "free_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml",
                "paid_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml",
                "comments_feed": "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml",
                "custom_emoji": "<:emoji_62:1365400946330435654>",
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

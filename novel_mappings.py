"""
novel_mappings.py

Mapping file for your own novel feed.
For each hosting site, we store:
  - translator: your username on that site.
  - host_logo: the URL for the site's logo.
  - novels: a dictionary mapping novel titles to their details:
      - discord_role_id: the Discord role ID for the novel.
      - novel_url: the manual URL for the novel.
      - featured_image: the URL for the novel's featured image.
      
Also included is a list (via get_nsfw_novels) for NSFW novels.
"""

HOSTING_SITE_DATA = {
    "Dragonholic": {
        "feed_url": "https://dragonholic.com/feed/manga-chapters/",
        "translator": "Cannibal Turtle",
        "host_logo": "https://dragonholic.com/wp-content/uploads/2025/01/Web-Logo-White.png",
        "novels": {
            "Quick Transmigration: The Villain Is Too Pampered and Alluring": {
                "discord_role_id": "<@&1329391480435114005>",
                "novel_url": "https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/",
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/177838.jpg",
                "pub_date_override": {"hour": 12, "minute": 0, "second": 0}
              
            },
            "Second Novel Title Example": {
                "discord_role_id": "<@&123456789012345678>",  # Replace with the actual Discord role ID.
                "novel_url": "https://dragonholic.com/second-novel",  # Replace with the manual URL for the second novel.
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/second-novel.jpg"
            },
            # Add more novels for Dragonholic here if needed.
        }
    },
    # Add other hosting sites here if needed.
}

def get_host_translator(host):
    """
    Returns the translator name for the given hosting site.
    """
    return HOSTING_SITE_DATA.get(host, {}).get("translator", "")

def get_host_logo(host):
    """
    Returns the hosting site's logo URL for the given host.
    """
    return HOSTING_SITE_DATA.get(host, {}).get("host_logo", "")

def get_novel_details(host, novel_title):
    """
    Returns the details of a novel (as a dict) from the specified hosting site.
    """
    return HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})

def get_novel_discord_role(novel_title, host="Dragonholic"):
    """
    Returns the Discord role ID for the given novel.
    If the novel title appears in the NSFW list (via get_nsfw_novels()),
    appends the extra role.
    """
    details = get_novel_details(host, novel_title)
    base_role = details.get("discord_role_id", "")
    if novel_title in get_nsfw_novels():
        base_role += " <@&1343352825811439616>"
    return base_role
  
def get_novel_url(novel_title, host="Dragonholic"):
    """
    Returns the URL for the given novel on the specified hosting site.
    """
    details = get_novel_details(host, novel_title)
    return details.get("novel_url", "")

def get_featured_image(novel_title, host="Dragonholic"):
    """
    Returns the featured image URL for the given novel on the specified hosting site.
    """
    details = get_novel_details(host, novel_title)
    return details.get("featured_image", "")

def get_nsfw_novels():
    """
    Returns the list of NSFW novel titles.
    Update this list if a novel is considered NSFW.
    """
    return [
        # Add NSFW novel titles here, e.g.:
        # "Some NSFW Novel Title"
    ]
# In novel_mappings.py, add the following helper function:

def get_pub_date_override(novel_title, host="Dragonholic"):
    """
    Returns a dictionary of pub_date override values (e.g. {"hour": 12, "minute": 0, "second": 0})
    for the given novel. If no override is defined, returns None.
    """
    details = get_novel_details(host, novel_title)
    return details.get("pub_date_override", None)

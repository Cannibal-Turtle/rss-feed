# novel_mappings.py
# Mapping dictionary for hosting site to their list of novel titles, translator, logo, discord roles, URLs, and novel covers.

HOSTING_SITE_DATA = {
    "Dragonholic": {
        "translator": "Cannibal Turtle",
        "host_logo": "https://dragonholic.com/wp-content/uploads/2025/01/Web-Logo-White.png",
        "novels": {
            "Quick Transmigration: The Villain Is Too Pampered and Alluring": {
                "discord_role_id": "<@&1286581623848046662>",
                "novel_url": "https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/",
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/177838.jpg"
            },
            "Second Novel Title Example": {
                "discord_role_id": "<@&123456789012345678>",  # Replace with the actual Discord role ID.
                "novel_url": "https://dragonholic.com/second-novel",  # Replace with the manual URL for the second novel.
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/second-novel.jpg"
            },
            # Add more novels here if needed.
        }
    },
    # Other hosting sites can be added here in the future.
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
    Details include:
      - discord_role_id
      - novel_url
      - featured_image
    If no details are found, returns an empty dictionary.
    """
    return HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})

def get_novel_discord_role(novel_title, host="Dragonholic"):
    """
    Returns the Discord role ID for the given novel on the specified hosting site.
    """
    details = get_novel_details(host, novel_title)
    return details.get("discord_role_id", "")

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
    Returns the list of NSFW novels.
    """
    return NSFW_NOVELS

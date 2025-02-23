"""
host_utils.py

This module contains host-specific utility functions for parsing chapter titles 
and extracting chapter numbers from RSS feed entries. These functions are used 
to handle the formatting conventions of different hosting sites.

Currently implemented:
  - For "Dragonholic": Titles are expected in the format:
      "Main Title - Chapter Name - (Optional Extension)"
  - For other hosts: A generic splitting on " - " is applied.
"""

import re

def split_title(host, full_title):
    """
    Splits the full title into three parts based on the host's formatting:
      - main_title: the main title of the work
      - chaptername: the chapter identifier
      - nameextend: an optional extension, if present

    For 'Dragonholic', the title is expected to be in the format:
      "Main Title - Chapter Name - (Optional Extension)"
    For other hosts, a generic split by " - " is used.

    Parameters:
      host (str): The hosting site name (e.g., "Dragonholic").
      full_title (str): The full title string from the RSS feed.
      
    Returns:
      tuple: (main_title, chaptername, nameextend)
    """
    if host == "Dragonholic":
        parts = full_title.split(" - ")
        if len(parts) == 2:
            main_title = parts[0].strip()
            chaptername = parts[1].strip()
            nameextend = ""
        elif len(parts) >= 3:
            main_title = parts[0].strip()
            chaptername = parts[1].strip()
            nameextend = parts[2].strip() if parts[2].strip() else (parts[3].strip() if len(parts) > 3 else "")
        else:
            main_title = full_title
            chaptername = ""
            nameextend = ""
        return main_title, chaptername, nameextend
    else:
        # Generic fallback: split on " - " and treat the remainder as the extension.
        parts = full_title.split(" - ")
        if len(parts) >= 2:
            main_title = parts[0].strip()
            chaptername = parts[1].strip()
            nameextend = " - ".join(parts[2:]).strip() if len(parts) > 2 else ""
            return main_title, chaptername, nameextend
        else:
            return full_title, "", ""

def chapter_num(host, chaptername):
    """
    Extracts numeric sequences from the chapter name based on host-specific rules.
    For 'Dragonholic', it extracts all numbers (as ints or floats) and returns them
    as a tuple, which can be used for sorting chapters.
    For other hosts, the same generic extraction is applied.

    Parameters:
      host (str): The hosting site name (e.g., "Dragonholic").
      chaptername (str): The chapter name portion of the title.
      
    Returns:
      tuple: A tuple of numbers extracted from the chapter name.
    """
    # Use similar logic for Dragonholic and generic fallback.
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    if not numbers:
        return (0,)
    return tuple(float(n) if '.' in n else int(n) for n in numbers)

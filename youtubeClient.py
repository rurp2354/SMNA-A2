import sys
from googleapiclient.discovery import build


def youtubeClient():
    """
    Create and return a YouTube Data API v3 client.
    """

    api_key = "INSERT_YOUR_API_KEY_HERE"

    if not api_key or api_key == "INSERT_YOUR_API_KEY_HERE":
        sys.stderr.write(
            "No YouTube API key found.\n"
            "Replace the placeholder in youtubeClient.py.\n"
        )
        sys.exit(1)

    try:
        youtube = build("youtube", "v3", developerKey=api_key)
    except Exception as e:
        sys.stderr.write(f"Failed to create YouTube client: {e}\n")
        sys.exit(1)

    return youtube
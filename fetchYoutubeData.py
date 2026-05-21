import csv
import json
import time
from pathlib import Path

from youtubeClient import youtubeClient


# ============================================================
# Settings
# ============================================================

SEARCH_QUERIES = [
    "Melbourne liveability",
    "living in Melbourne",
    "Melbourne cost of living",
    "Melbourne housing affordability",
    "Melbourne public transport",
    "Melbourne quality of life",
    "is Melbourne a good place to live",
    "Melbourne vs Sydney living"
]

MAX_VIDEOS_PER_QUERY = 5
MAX_TOP_LEVEL_COMMENTS_PER_VIDEO = 200
MAX_REPLIES_PER_COMMENT = 100
OUTPUT_STEM = "melbourne_liveability_youtube"

# Optional: restrict to more recent videos if needed
PUBLISHED_AFTER = None
# Example:
# PUBLISHED_AFTER = "2024-01-01T00:00:00Z"


# ============================================================
# Helpers
# ============================================================

def chunks(items, size):
    """Yield successive chunks from a list."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def safe_author_channel_id(snippet):
    """
    Use a stable user identifier where possible.
    Falls back to display name if channel ID is missing.
    """
    author_channel = snippet.get("authorChannelId")

    if isinstance(author_channel, dict):
        value = author_channel.get("value")
        if value:
            return value

    display_name = snippet.get("authorDisplayName", "unknown")
    return f"name::{display_name}"


def search_videos(client, query, max_videos=10, published_after=None):
    """
    Search YouTube for videos matching a query.
    """
    params = {
        "q": query,
        "part": "snippet",
        "type": "video",
        "order": "relevance",
        "maxResults": min(max_videos, 50),
        "regionCode": "AU",
        "relevanceLanguage": "en"
    }

    if published_after:
        params["publishedAfter"] = published_after

    response = client.search().list(**params).execute()

    results = []
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]

        results.append({
            "videoId": video_id,
            "title": snippet.get("title", ""),
            "channelTitle": snippet.get("channelTitle", ""),
            "publishedAt": snippet.get("publishedAt", ""),
            "description": snippet.get("description", ""),
            "matchedQuery": query
        })

    return results


def fetch_video_metadata(client, video_ids):
    """
    Fetch detailed metadata for a list of video IDs.
    """
    metadata = {}

    for batch in chunks(video_ids, 50):
        response = client.videos().list(
            id=",".join(batch),
            part="snippet,statistics"
        ).execute()

        for item in response.get("items", []):
            video_id = item["id"]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})

            metadata[video_id] = {
                "videoId": video_id,
                "title": snippet.get("title", ""),
                "channelTitle": snippet.get("channelTitle", ""),
                "publishedAt": snippet.get("publishedAt", ""),
                "description": snippet.get("description", ""),
                "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
                "commentCount": int(stats.get("commentCount", 0))
            }

    return metadata


def fetch_all_replies(
    client,
    parent_comment_id,
    video_id,
    parent_author_channel_id,
    parent_author_display_name,
    max_replies_per_comment=100
):
    """
    Fetch all replies for a given top-level comment.
    """
    replies = []
    next_page_token = None

    while len(replies) < max_replies_per_comment:
        remaining = max_replies_per_comment - len(replies)
        request_size = min(100, remaining)

        response = client.comments().list(
            part="id,snippet",
            parentId=parent_comment_id,
            maxResults=request_size,
            textFormat="plainText",
            pageToken=next_page_token
        ).execute()

        for item in response.get("items", []):
            snippet = item["snippet"]

            replies.append({
                "commentId": item.get("id"),
                "parentCommentId": parent_comment_id,
                "videoId": video_id,
                "isReply": True,
                "authorChannelId": safe_author_channel_id(snippet),
                "authorDisplayName": snippet.get("authorDisplayName", ""),
                "text": snippet.get("textDisplay", ""),
                "publishedAt": snippet.get("publishedAt", ""),
                "likeCount": snippet.get("likeCount", 0),
                "totalReplyCount": 0,
                "parentAuthorChannelId": parent_author_channel_id,
                "parentAuthorDisplayName": parent_author_display_name
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

        time.sleep(0.1)

    return replies


def fetch_comments_for_video(
    client,
    video_id,
    max_top_level_comments=200,
    max_replies_per_comment=100
):
    """
    Fetch top-level comments and replies for one video.
    """
    all_comments = []
    next_page_token = None
    top_level_count = 0

    while top_level_count < max_top_level_comments:
        remaining = max_top_level_comments - top_level_count
        request_size = min(100, remaining)

        response = client.commentThreads().list(
            videoId=video_id,
            part="id,snippet",
            maxResults=request_size,
            textFormat="plainText",
            pageToken=next_page_token,
            order="relevance"
        ).execute()

        items = response.get("items", [])
        if not items:
            break

        for thread in items:
            top_level_comment = thread["snippet"]["topLevelComment"]
            snippet = top_level_comment["snippet"]

            comment_id = top_level_comment.get("id")
            parent_author_channel_id = safe_author_channel_id(snippet)
            parent_author_display_name = snippet.get("authorDisplayName", "")

            all_comments.append({
                "commentId": comment_id,
                "parentCommentId": None,
                "videoId": video_id,
                "isReply": False,
                "authorChannelId": parent_author_channel_id,
                "authorDisplayName": parent_author_display_name,
                "text": snippet.get("textDisplay", ""),
                "publishedAt": snippet.get("publishedAt", ""),
                "likeCount": snippet.get("likeCount", 0),
                "totalReplyCount": thread["snippet"].get("totalReplyCount", 0),
                "parentAuthorChannelId": None,
                "parentAuthorDisplayName": None
            })

            top_level_count += 1

            total_replies = thread["snippet"].get("totalReplyCount", 0)
            if total_replies > 0 and max_replies_per_comment > 0:
                try:
                    replies = fetch_all_replies(
                        client=client,
                        parent_comment_id=comment_id,
                        video_id=video_id,
                        parent_author_channel_id=parent_author_channel_id,
                        parent_author_display_name=parent_author_display_name,
                        max_replies_per_comment=max_replies_per_comment
                    )
                    all_comments.extend(replies)
                except Exception as e:
                    print(f"    Failed to fetch replies for comment {comment_id}: {e}")

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

        time.sleep(0.1)

    return all_comments


# ============================================================
# CSV / Output saving
# ============================================================

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def save_flat_outputs(data, output_dir, output_stem):
    """
    Save:
      - videos CSV
      - comments CSV
      - user-video edge CSV
      - reply edge CSV
    """
    videos_rows = []
    comments_rows = []
    user_video_edges = set()
    reply_edges = set()

    for video in data["videos"]:
        videos_rows.append({
            "videoId": video["videoId"],
            "title": video["title"],
            "channelTitle": video["channelTitle"],
            "publishedAt": video["publishedAt"],
            "viewCount": video["viewCount"],
            "likeCount": video["likeCount"],
            "commentCount": video["commentCount"],
            "matchedQueries": " | ".join(video.get("matchedQueries", []))
        })

        for comment in video["comments"]:
            comments_rows.append({
                "videoId": video["videoId"],
                "videoTitle": video["title"],
                "channelTitle": video["channelTitle"],
                "commentId": comment["commentId"],
                "parentCommentId": comment["parentCommentId"],
                "isReply": comment["isReply"],
                "authorChannelId": comment["authorChannelId"],
                "authorDisplayName": comment["authorDisplayName"],
                "text": comment["text"],
                "publishedAt": comment["publishedAt"],
                "likeCount": comment["likeCount"],
                "totalReplyCount": comment["totalReplyCount"],
                "parentAuthorChannelId": comment["parentAuthorChannelId"],
                "parentAuthorDisplayName": comment["parentAuthorDisplayName"]
            })

            user_video_edges.add((
                comment["authorChannelId"],
                comment["authorDisplayName"],
                video["videoId"],
                video["title"]
            ))

            if comment["isReply"]:
                reply_edges.add((
                    comment["authorChannelId"],
                    comment["authorDisplayName"],
                    comment["parentAuthorChannelId"],
                    comment["parentAuthorDisplayName"],
                    video["videoId"],
                    comment["parentCommentId"]
                ))

    videos_csv = output_dir / f"{output_stem}_videos.csv"
    comments_csv = output_dir / f"{output_stem}_comments.csv"
    user_video_csv = output_dir / f"{output_stem}_user_video_edges.csv"
    reply_edges_csv = output_dir / f"{output_stem}_reply_edges.csv"

    write_csv(
        videos_csv,
        videos_rows,
        [
            "videoId", "title", "channelTitle", "publishedAt",
            "viewCount", "likeCount", "commentCount", "matchedQueries"
        ]
    )

    write_csv(
        comments_csv,
        comments_rows,
        [
            "videoId", "videoTitle", "channelTitle", "commentId",
            "parentCommentId", "isReply", "authorChannelId",
            "authorDisplayName", "text", "publishedAt", "likeCount",
            "totalReplyCount", "parentAuthorChannelId",
            "parentAuthorDisplayName"
        ]
    )

    write_csv(
        user_video_csv,
        [
            {
                "authorChannelId": row[0],
                "authorDisplayName": row[1],
                "videoId": row[2],
                "videoTitle": row[3]
            }
            for row in sorted(user_video_edges)
        ],
        ["authorChannelId", "authorDisplayName", "videoId", "videoTitle"]
    )

    write_csv(
        reply_edges_csv,
        [
            {
                "replyAuthorChannelId": row[0],
                "replyAuthorDisplayName": row[1],
                "parentAuthorChannelId": row[2],
                "parentAuthorDisplayName": row[3],
                "videoId": row[4],
                "parentCommentId": row[5]
            }
            for row in sorted(reply_edges)
        ],
        [
            "replyAuthorChannelId", "replyAuthorDisplayName",
            "parentAuthorChannelId", "parentAuthorDisplayName",
            "videoId", "parentCommentId"
        ]
    )

    print(f"Saved videos CSV to: {videos_csv}")
    print(f"Saved comments CSV to: {comments_csv}")
    print(f"Saved user-video edge CSV to: {user_video_csv}")
    print(f"Saved reply edge CSV to: {reply_edges_csv}")


# ============================================================
# Search-based collection
# ============================================================

def collect_youtube_dataset(
    search_queries,
    max_videos_per_query=5,
    max_top_level_comments_per_video=50,
    max_replies_per_comment=20,
    output_stem="melbourne_liveability_youtube",
    published_after=None
):
    client = youtubeClient()

    print("Searching for candidate videos...")

    video_query_map = {}
    candidate_video_ids = []

    for query in search_queries:
        print(f"  Query: {query}")
        results = search_videos(
            client=client,
            query=query,
            max_videos=max_videos_per_query,
            published_after=published_after
        )

        for result in results:
            vid = result["videoId"]

            if vid not in video_query_map:
                video_query_map[vid] = {
                    "matchedQueries": [query]
                }
                candidate_video_ids.append(vid)
            else:
                video_query_map[vid]["matchedQueries"].append(query)

    print(f"Found {len(candidate_video_ids)} unique videos across all queries.")

    print("Fetching video metadata...")
    video_metadata = fetch_video_metadata(client, candidate_video_ids)

    print("Fetching comments and replies...")

    videos = []
    for idx, video_id in enumerate(candidate_video_ids, start=1):
        metadata = video_metadata.get(video_id)
        if not metadata:
            continue

        print(f"[{idx}/{len(candidate_video_ids)}] {metadata['title'][:70]}")

        video_record = {
            **metadata,
            "matchedQueries": video_query_map[video_id]["matchedQueries"],
            "comments": []
        }

        try:
            video_record["comments"] = fetch_comments_for_video(
                client=client,
                video_id=video_id,
                max_top_level_comments=max_top_level_comments_per_video,
                max_replies_per_comment=max_replies_per_comment
            )
            n_top = sum(1 for c in video_record["comments"] if not c["isReply"])
            n_rep = sum(1 for c in video_record["comments"] if c["isReply"])
            print(f"    Top-level: {n_top} | Replies: {n_rep}")

        except Exception as e:
            print(f"    Comments disabled or fetch failed: {e}")

        videos.append(video_record)
        time.sleep(0.1)

    data = {"videos": videos}

    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_json_path = output_dir / f"{output_stem}_raw.json"
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved raw JSON to: {raw_json_path}")

    save_flat_outputs(data, output_dir, output_stem)

    return data


# ============================================================
# Curated video-ID collection
# ============================================================

def collect_youtube_dataset_by_video_ids(
    video_ids,
    max_top_level_comments_per_video=200,
    max_replies_per_comment=100,
    output_stem="melbourne_liveability_youtube_curated_v1"
):
    """
    Collect data for a manually curated list of YouTube video IDs.
    Saves:
      - raw JSON
      - videos CSV
      - comments CSV
      - user-video edge CSV
      - reply edge CSV
    """
    client = youtubeClient()

    print(f"Fetching {len(video_ids)} curated videos...")

    video_metadata = fetch_video_metadata(client, video_ids)

    videos = []
    for idx, video_id in enumerate(video_ids, start=1):
        metadata = video_metadata.get(video_id)

        if not metadata:
            print(f"[{idx}/{len(video_ids)}] Video metadata not found for {video_id}")
            continue

        print(f"[{idx}/{len(video_ids)}] {metadata['title'][:70]}")

        video_record = {
            **metadata,
            "matchedQueries": ["MANUAL_CURATED"],
            "comments": []
        }

        try:
            video_record["comments"] = fetch_comments_for_video(
                client=client,
                video_id=video_id,
                max_top_level_comments=max_top_level_comments_per_video,
                max_replies_per_comment=max_replies_per_comment
            )

            n_top = sum(1 for c in video_record["comments"] if not c["isReply"])
            n_rep = sum(1 for c in video_record["comments"] if c["isReply"])
            print(f"    Top-level: {n_top} | Replies: {n_rep}")

        except Exception as e:
            print(f"    Comments disabled or fetch failed: {e}")

        videos.append(video_record)
        time.sleep(0.1)

    data = {"videos": videos}

    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_json_path = output_dir / f"{output_stem}_raw.json"
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved raw JSON to: {raw_json_path}")

    save_flat_outputs(data, output_dir, output_stem)

    return data


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    KEEP_VIDEO_IDS = [
        "oUqavm7KhGg",
        "AbtyFah6fPY",
        "YJotR0AltBI",
        "FJbmy95XZCk",
        "y9bkNPS02O4",
        "zFtV07Rk5i4",
        "iQBWhf2WvG8",
        "x3tHUfo05Ds",
        "aUJBIrElRSk",
        "2SvmQgb5S74",
        "ea14oVK8XLw",
        "dVbSXe4Nc34",
        "MzgZV6CKDL4",
        "jquzABCA-dg",
        "MnJziG3Dri0",
        "HRP1t-P0Ljw",
        "GMx9oXxHMXE",
        "JhRWS4S5rEg",
        "5ByeB4u-jDU",
        "5GNK1mQDnzk",
        "FSOnKtQa-j8",
        "_5P63Icg7iU",
        "UU0e1DODX7Y",
        "mFZPawD_TAk",
        "iwiAxppxGaU",
        "PROvfUw9o3o"
    ]

    MAX_TOP_LEVEL_COMMENTS_PER_VIDEO = 200
    MAX_REPLIES_PER_COMMENT = 100
    OUTPUT_STEM = "melbourne_liveability_youtube_curated_v1"

    collect_youtube_dataset_by_video_ids(
        video_ids=KEEP_VIDEO_IDS,
        max_top_level_comments_per_video=MAX_TOP_LEVEL_COMMENTS_PER_VIDEO,
        max_replies_per_comment=MAX_REPLIES_PER_COMMENT,
        output_stem=OUTPUT_STEM
    )
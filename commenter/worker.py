"""Comment boost worker — sends reply comments to a tweet using a pool of accounts.

All functions are synchronous (uses curl_cffi + threading).
Designed to be called from ``asyncio.to_thread()``.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Any

import curl_cffi
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# X API helpers (kept verbatim from reference — headers/payloads unchanged)
# ---------------------------------------------------------------------------

_BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


def _x_client_transaction_id(session: curl_requests.Session) -> Any:
    """Fetch x.com homepage and build a ClientTransaction generator."""
    from bs4 import BeautifulSoup
    from x_client_transaction import ClientTransaction
    from x_client_transaction.utils import get_ondemand_file_url

    headers = {
        "Authority": "x.com",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Referer": "https://x.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Client-Language": "en",
    }

    home_page = None
    for attempt in range(3):
        try:
            home_page = session.get("https://x.com", headers=headers)
            break
        except Exception:
            if attempt == 2:
                return False
            time.sleep(0)

    try:
        home_page_response = BeautifulSoup(home_page.content, "html.parser")
        ondemand_file_url = get_ondemand_file_url(response=home_page_response)
        ondemand_file = session.get(url=ondemand_file_url)
        xtid_lib = ClientTransaction(
            home_page_response=home_page_response,
            ondemand_file_response=ondemand_file.text,
        )
        return xtid_lib
    except Exception:
        return ""


def _auth_to_ct0(session: curl_requests.Session, auth: str) -> str | bool:
    """Obtain ct0 CSRF token from auth_token. Returns ct0 string or False."""
    headers = {
        "Host": "twitter.com",
        "Sec-Ch-Ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "X-Requested-With": "com.twitter.android",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Encoding": "utf-8",
        "Accept-Language": "en-US,en;q=0.9",
        "Priority": "u=0, i",
        "Cookie": f"auth_token={auth};",
    }
    for attempt in range(3):
        try:
            ct0_response = session.post(
                "https://twitter.com/i/api/1.1/account/update_profile.json",
                headers=headers,
            )
            return ct0_response.cookies["ct0"]
        except Exception:
            if attempt == 2:
                return False
            time.sleep(0)
    return False


def _comment(
    session: curl_requests.Session,
    ct0: str,
    auth_token: str,
    tweetid: str,
    comment_text: str,
    retries: int = 3,
) -> str | bool:
    """Post a reply comment to a tweet. Returns rest_id on success, False on failure."""
    xclienttid = _x_client_transaction_id(session)

    for attempt in range(retries):
        try:
            url = "https://x.com/i/api/graphql/UYy4T67XpYXgWKOafKXB_A/CreateTweet"

            headers = {
                "Accept": "*/*",
                "Accept-Encoding": "utf-8",
                "Accept-Language": "en-US,en;q=0.9",
                "Authorization": _BEARER,
                "Cookie": f"ct0={ct0};auth_token={auth_token}",
                "Origin": "https://x.com",
                "Referer": "https://x.com/",
                "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
                "x-client-transaction-id": xclienttid.generate_transaction_id(
                    method="POST",
                    path="/i/api/graphql/UYy4T67XpYXgWKOafKXB_A/CreateTweet",
                ),
                "x-csrf-token": ct0,
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "x-twitter-client-language": "en",
            }

            data = {
                "variables": {
                    "tweet_text": comment_text,
                    "reply": {
                        "in_reply_to_tweet_id": tweetid,
                        "exclude_reply_user_ids": [],
                    },
                    "dark_request": False,
                    "media": {
                        "media_entities": [],
                        "possibly_sensitive": False,
                    },
                    "semantic_annotation_ids": [],
                    "disallowed_reply_options": None,
                },
                "features": {
                    "premium_content_api_read_enabled": False,
                    "communities_web_enable_tweet_community_results_fetch": True,
                    "c9s_tweet_anatomy_moderator_badge_enabled": True,
                    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
                    "responsive_web_grok_analyze_post_followups_enabled": True,
                    "responsive_web_jetfuel_frame": False,
                    "responsive_web_grok_share_attachment_enabled": True,
                    "responsive_web_edit_tweet_api_enabled": True,
                    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                    "view_counts_everywhere_api_enabled": True,
                    "longform_notetweets_consumption_enabled": True,
                    "responsive_web_twitter_article_tweet_consumption_enabled": True,
                    "tweet_awards_web_tipping_enabled": False,
                    "responsive_web_grok_analysis_button_from_backend": True,
                    "creator_subscriptions_quote_tweet_preview_enabled": False,
                    "longform_notetweets_rich_text_read_enabled": True,
                    "longform_notetweets_inline_media_enabled": True,
                    "profile_label_improvements_pcf_label_in_post_enabled": True,
                    "rweb_tipjar_consumption_enabled": True,
                    "responsive_web_graphql_exclude_directive_enabled": True,
                    "verified_phone_label_enabled": False,
                    "articles_preview_enabled": True,
                    "rweb_video_timestamps_enabled": True,
                    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                    "freedom_of_speech_not_reach_fetch_enabled": True,
                    "standardized_nudges_misinfo": True,
                    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                    "responsive_web_grok_image_annotation_enabled": True,
                    "responsive_web_graphql_timeline_navigation_enabled": True,
                    "responsive_web_enhance_cards_enabled": False,
                },
                "queryId": "UYy4T67XpYXgWKOafKXB_A",
            }

            response = session.post(url, headers=headers, json=data)
            resp_data = response.json()

            if "errors" in resp_data:
                return False

            try:
                rest_id = resp_data["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
                return rest_id
            except (KeyError, json.JSONDecodeError):
                return False

        except Exception:
            time.sleep(0)

    return False


# ---------------------------------------------------------------------------
# Threaded worker
# ---------------------------------------------------------------------------


def _worker(
    token_value: str,
    proxy: str,
    tweet_id: str,
    comment_limit: int,
    per_acc_comment: int,
    comment_texts: list[str],
    counter: dict,
    lock: threading.Lock,
    expired_accounts: list[str],
    failed_counter: dict,
    mark_invalid_fn: Any,
) -> None:
    """Single-account worker thread."""
    if proxy:
        proxy_url = f"http://{proxy}" if not proxy.startswith("http") else proxy
        session = curl_cffi.Session(
            impersonate="chrome136",
            proxies={"http": proxy_url, "https": proxy_url},
        )
    else:
        session = curl_cffi.Session(impersonate="chrome136")

    auth_token = token_value

    ct0 = _auth_to_ct0(session, auth_token)
    if ct0 is False:
        logger.warning("Comment account %s... — ct0 failed (expired)", auth_token[:8])
        with lock:
            expired_accounts.append(auth_token)
            failed_counter["count"] += 1
        if mark_invalid_fn:
            mark_invalid_fn(auth_token)
        return

    for _ in range(per_acc_comment):
        with lock:
            can_comment = counter["count"] < comment_limit

        if not can_comment:
            break

        scomment = random.choice(comment_texts)
        res = _comment(session, ct0, auth_token, tweet_id, scomment)

        with lock:
            if res:
                counter["count"] += 1
            else:
                failed_counter["count"] += 1

        time.sleep(random.randint(1, 3))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_comment_boost(tweet_id: str, comment_pool: Any) -> dict[str, Any]:
    """Run comment boost for a tweet. SYNCHRONOUS — call via asyncio.to_thread().

    Returns dict: {"sent": N, "failed": N, "target": N, "expired_accounts": [...]}
    """
    from commenter.pool import CommentPool

    pool: CommentPool = comment_pool

    accounts = pool.get_valid_accounts()
    texts = pool.texts
    total_range = pool.total_range
    per_acc = pool.per_acc_comments
    proxy = pool.proxy

    if not accounts:
        return {"sent": 0, "failed": 0, "target": 0, "expired_accounts": []}
    if not texts:
        return {"sent": 0, "failed": 0, "target": 0, "expired_accounts": []}

    comment_limit = random.randint(total_range[0], total_range[1])

    # Shuffle accounts
    account_values = [a["value"] for a in accounts]
    random.shuffle(account_values)

    # Shared state
    counter: dict[str, int] = {"count": 0}
    failed_counter: dict[str, int] = {"count": 0}
    expired: list[str] = []
    lock = threading.Lock()

    logger.info(
        "Comment boost starting: tweet=%s, target=%d, accounts=%d, per_acc=%d",
        tweet_id, comment_limit, len(account_values), per_acc,
    )

    threads = []
    for token_val in account_values:
        t = threading.Thread(
            target=_worker,
            args=(
                token_val, proxy, tweet_id, comment_limit,
                per_acc, texts, counter, lock, expired, failed_counter,
                pool.mark_invalid,
            ),
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    result = {
        "sent": counter["count"],
        "failed": failed_counter["count"],
        "target": comment_limit,
        "expired_accounts": expired,
    }
    logger.info("Comment boost done: %s", result)
    return result

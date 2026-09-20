#!/usr/bin/env python3
"""
Get a YouTube OAuth refresh token for Lavalink's youtube-plugin.

Run it, open the link it prints, enter the code, and it prints the refresh token
to paste into application.yml.

    ./scripts/get-youtube-token.py

Use a throwaway Google account. Google may flag or lock accounts used this way,
and the token grants the plugin access to that account's YouTube.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Public client credentials for the YouTube on TV device flow. These are not
# secret; they ship inside the TV app and are what youtube-plugin expects.
CLIENT_ID = "861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com"
CLIENT_SECRET = "SboVhoG9s0rNafixCSGGKXAT"
SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def post(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    try:
        device = post(DEVICE_URL, {"client_id": CLIENT_ID, "scope": SCOPE})
    except urllib.error.URLError as e:
        print(f"Could not reach Google: {e}", file=sys.stderr)
        return 1

    print()
    print("  1. Open this link:  " + device["verification_url"])
    print("  2. Enter this code: " + device["user_code"])
    print(f"  3. Approve access. The code expires in {device['expires_in'] // 60} minutes.")
    print()
    print("  Waiting for approval, leave this running ...")

    interval = device.get("interval", 5)
    deadline = time.time() + device["expires_in"]

    while time.time() < deadline:
        time.sleep(interval)
        try:
            token = post(TOKEN_URL, {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "device_code": device["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if "authorization_pending" in body:
                continue
            if "slow_down" in body:
                interval += 5
                continue
            if "access_denied" in body:
                print("\n  Access was denied. Run the script again to retry.", file=sys.stderr)
                return 1
            if "expired_token" in body:
                print("\n  The code expired. Run the script again.", file=sys.stderr)
                return 1
            print(f"\n  Unexpected error from Google: {body[:200]}", file=sys.stderr)
            return 1

        if "refresh_token" in token:
            print()
            print("  Success. Your refresh token:")
            print()
            print("    " + token["refresh_token"])
            print()
            print("  Paste it into application.yml, replacing YOUTUBE_OAUTH_REFRESH_TOKEN:")
            print()
            print("      oauth:")
            print("        enabled: true")
            print('        refreshToken: "PASTE_IT_HERE"')
            print("        skipInitialization: true")
            print()
            print("  Then restart Lavalink. Keep this token private, it is a login credential.")
            return 0

    print("\n  Timed out waiting for approval. Run the script again.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)

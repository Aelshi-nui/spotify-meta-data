#!/usr/bin/env python3
"""
Lavalink PLAYBACK tester.

Why this exists: /v4/loadtracks only proves a track RESOLVES (metadata).
It passed on every broken YouTube build we debugged. Actual streaming is a
separate stage, and the only way to test it is to attach a player over the
websocket and watch for TrackStartEvent vs TrackExceptionEvent.

Usage:
  ./playtest.py --host localhost:2333 --password YOUR_PASSWORD
  ./playtest.py --host node.example.com:2333 --password YOUR_PASSWORD --set youtube
  ./playtest.py --host node.example.com:2333 --password YOUR_PASSWORD \
      --id "spsearch:blinding lights" --id "amzsearch:drake"

Notes:
  * needs:  pip install websockets
  * do NOT validate YouTube on dQw4w9WgXcQ alone - the upstream PR author
    warned it passes even on broken builds. Use --set youtube.
  * a pass means "started AND survived --grace seconds". TrackStartEvent on its
    own is not playback: Lavalink fires it when the track is assigned, and the
    YouTube source only resolves a stream format afterwards, which is where a
    broken build throws. Treating TrackStartEvent as success is what made this
    script report 6/6 on a node where half the videos actually fail.
"""
import argparse, asyncio, json, sys, urllib.error, urllib.parse, urllib.request

# YouTube videos that exposed real breakage before (login wall / cipher).
YOUTUBE_SET = [
    "https://www.youtube.com/watch?v=UrCcDPTyWms",
    "https://www.youtube.com/watch?v=mWdwsmgfuzY",
    "https://www.youtube.com/watch?v=kJQP7kiw5Fk",
    "https://www.youtube.com/watch?v=8CFh_-qtzeg",
    "https://www.youtube.com/watch?v=YC-QnlIEbJU",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
]
# One probe per source, to catch a single source regressing.
SOURCES_SET = [
    "spsearch:blinding lights",
    "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "amsearch:animals architects",
    "amzsearch:blinding lights",
    "gaanasearch:arijit singh",
    "ytsearch:never gonna give you up",
    "scsearch:flume never be like you",
]


def make_rest(base, password):
    def rest(path, method="GET", body=None):
        req = urllib.request.Request(
            base + path, method=method,
            headers={"Authorization": password, "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body else None,
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    return rest


def first_encoded(rest, identifier):
    """Resolve an identifier to a playable `encoded` track, or (None, reason)."""
    q = urllib.parse.quote(identifier, safe="")
    d = rest(f"/v4/loadtracks?identifier={q}")
    lt = d["loadType"]
    if lt == "track":
        return d["data"]["encoded"], d["data"]["info"]["title"]
    if lt == "search" and d["data"]:
        return d["data"][0]["encoded"], d["data"][0]["info"]["title"]
    if lt == "playlist" and d["data"]["tracks"]:
        t = d["data"]["tracks"][0]
        return t["encoded"], t["info"]["title"]
    if lt == "error":
        return None, "LOAD-ERROR: " + str(d["data"].get("message"))[:44]
    return None, f"LOAD-{lt.upper()}"


async def run(host, password, identifiers, timeout, guild_base, grace):
    import websockets  # imported here so --help works without the dep
    base = f"http://{host}"
    rest = make_rest(base, password)
    try:
        rest("/v4/info")
    except urllib.error.HTTPError as e:
        print(f"  cannot reach {host}: HTTP {e.code} "
              f"({'wrong password' if e.code in (401, 403) else e.reason})")
        return 1
    except Exception as e:
        print(f"  cannot reach {host}: {e}")
        return 1

    async with websockets.connect(
        f"ws://{host}/v4/websocket",
        additional_headers={"Authorization": password,
                            "User-Id": "999999999999999999",
                            "Client-Name": "playtest/1.0"},
        ping_interval=None,
    ) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), 30))
        sid = ready["sessionId"]
        print(f"  session {sid} on {host}\n")

        guild = guild_base
        passed = 0
        for ident in identifiers:
            encoded, title = first_encoded(rest, ident)
            label = ident if len(ident) <= 44 else ident[:41] + "..."
            if not encoded:
                print(f"  {label:46} {title}")
                continue

            guild += 1
            rest(f"/v4/sessions/{sid}/players/{guild}?noReplace=false",
                 "PATCH", {"track": {"encoded": encoded}})

            verdict = f"TIMEOUT (no event in {timeout}s)"
            try:
                # TrackStartEvent is NOT proof of playback. Lavalink emits it when
                # the track is assigned to the player; the YouTube source then
                # resolves a stream format, and that is the stage that throws
                # AllClientsFailedException / ScriptExtractionException a fraction
                # of a second later. Breaking on TrackStartEvent therefore reports
                # PLAYS for a track that is about to fail - the exact false pass
                # this script's docstring warns about. Verified against
                # a live node on 2026-09-14: kJQP7kiw5Fk reported PLAYS but
                # throws AllClientsFailedException ~0.2s after starting.
                #
                # So: wait for the start, then keep listening for `grace` seconds
                # and only call it a pass if nothing blew up in that window.
                started = False
                deadline = asyncio.get_event_loop().time() + timeout
                while True:
                    now = asyncio.get_event_loop().time()
                    if now >= deadline:
                        break
                    msg = json.loads(await asyncio.wait_for(ws.recv(), deadline - now))
                    if msg.get("op") != "event" or str(msg.get("guildId")) != str(guild):
                        continue
                    t = msg["type"]
                    if t == "TrackStartEvent":
                        started = True
                        verdict = "PLAYS"
                        # Shorten the window to the grace period and keep reading.
                        deadline = min(deadline, asyncio.get_event_loop().time() + grace)
                        continue
                    if t == "TrackExceptionEvent":
                        detail = str(msg["exception"].get("message"))[:40]
                        verdict = ("STARTED then EXCEPTION: " if started
                                   else "EXCEPTION: ") + detail
                        break
                    if t == "TrackStuckEvent":
                        verdict = "STUCK"
                        break
                    if t == "TrackEndEvent" and msg.get("reason") == "loadFailed":
                        verdict = "LOAD-FAILED after start" if started else "LOAD-FAILED"
                        break
            except asyncio.TimeoutError:
                pass

            if verdict == "PLAYS":
                passed += 1
            print(f"  {label:46} {verdict}   [{title[:26]}]")

            try:
                rest(f"/v4/sessions/{sid}/players/{guild}", "DELETE")
            except Exception:
                pass

        total = len(identifiers)
        print(f"\n  PLAYBACK: {passed}/{total} passing")
        return 0 if passed == total else 2


def main():
    p = argparse.ArgumentParser(description="Test Lavalink actual playback, not just resolution.")
    p.add_argument("--host", default="localhost:2333", help="host:port (default localhost:2333)")
    p.add_argument("--password", required=True, help="Lavalink server password")
    p.add_argument("--set", choices=["youtube", "sources"], default="youtube",
                   help="youtube = the 6 known-tricky videos; sources = one probe per source")
    p.add_argument("--id", action="append", dest="ids", metavar="IDENTIFIER",
                   help="explicit identifier (repeatable); overrides --set")
    p.add_argument("--timeout", type=int, default=40, help="per-track event wait (default 40s)")
    p.add_argument("--grace", type=float, default=6.0,
                   help="seconds to keep listening after TrackStartEvent before "
                        "calling it a pass (default 6). A broken YouTube build "
                        "starts a track and throws a moment later, so a grace of 0 "
                        "reproduces the old false-pass behaviour.")
    p.add_argument("--guild-base", type=int, default=9000, help="starting fake guild id")
    a = p.parse_args()

    identifiers = a.ids if a.ids else (YOUTUBE_SET if a.set == "youtube" else SOURCES_SET)
    try:
        sys.exit(asyncio.run(run(a.host, a.password, identifiers, a.timeout,
                                 a.guild_base, a.grace)))
    except ModuleNotFoundError:
        print("  missing dependency: pip install websockets")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

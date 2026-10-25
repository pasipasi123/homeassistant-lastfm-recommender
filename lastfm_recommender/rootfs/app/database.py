"""SQLite storage; one connection per operation, atomic page checkpoints."""
import calendar
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def album_tags(tags):
    """Year tags are album metadata, not genres; conflicting years stay unknown."""
    cleaned = {normalized(tag) for tag in tags if tag.strip()}
    years = {int(tag) for tag in cleaned if re.fullmatch(r"[12][0-9]{3}", tag)}
    return sorted(tag for tag in cleaned if not re.fullmatch(r"[12][0-9]{3}", tag)), (
        next(iter(years)) if len(years) == 1 else None), bool(years)


def calendar_cutoff(years, now=None):
    """Calendar years in UTC; February 29 clamps to February 28."""
    now = now or datetime.now(timezone.utc)
    year = now.year - years
    day = min(now.day, calendar.monthrange(year, now.month)[1])
    return int(now.replace(year=year, day=day).timestamp())


def spotify_uri(value):
    match = re.fullmatch(r"spotify:album:([A-Za-z0-9]{22})", value.strip())
    if not match:
        match = re.fullmatch(
            r"https://open\.spotify\.com/(?:intl-[a-z]{2}/)?album/([A-Za-z0-9]{22})/?(?:\?[^\s]*)?",
            value.strip(),
        )
    if not match:
        raise ValueError("Use a Spotify album URI or an https://open.spotify.com/album/ link")
    return "spotify:album:" + match[1]


class Database:
    def __init__(self, path, tz="Europe/Helsinki"):
        self.path = str(path)
        self.tz = ZoneInfo(tz)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("Unsupported database schema version")
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS albums (
                    id INTEGER PRIMARY KEY, artist TEXT NOT NULL, album TEXT NOT NULL,
                    artist_search TEXT NOT NULL, album_search TEXT NOT NULL,
                    mbid TEXT NOT NULL DEFAULT '', image_url TEXT,
                    spotify_uri TEXT, spotify_status TEXT NOT NULL DEFAULT 'missing',
                    spotify_candidate TEXT, enriched_at INTEGER,
                    scrobbles_total INTEGER NOT NULL DEFAULT 0, last_listened_at INTEGER,
                    UNIQUE(artist, album)
                );
                CREATE TABLE IF NOT EXISTS scrobbles (
                    id INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL,
                    artist TEXT NOT NULL, album TEXT NOT NULL, track TEXT NOT NULL,
                    track_mbid TEXT NOT NULL DEFAULT '', album_id INTEGER REFERENCES albums(id),
                    occurrence INTEGER NOT NULL, year INTEGER NOT NULL,
                    month INTEGER NOT NULL, day_of_week INTEGER NOT NULL, hour INTEGER NOT NULL,
                    UNIQUE(timestamp, artist, album, track, occurrence)
                );
                CREATE INDEX IF NOT EXISTS scrobbles_time ON scrobbles(timestamp);
                CREATE INDEX IF NOT EXISTS scrobbles_album ON scrobbles(album_id);
                CREATE INDEX IF NOT EXISTS scrobbles_context ON scrobbles(day_of_week, hour, album_id);
                CREATE INDEX IF NOT EXISTS albums_last ON albums(last_listened_at);
                CREATE TABLE IF NOT EXISTS album_tags (
                    album_id INTEGER NOT NULL REFERENCES albums(id), tag TEXT NOT NULL,
                    PRIMARY KEY(album_id, tag)
                );
                CREATE INDEX IF NOT EXISTS tags_tag ON album_tags(tag);
                CREATE TABLE IF NOT EXISTS import_seen (
                    timestamp INTEGER NOT NULL, artist TEXT NOT NULL, album TEXT NOT NULL,
                    track TEXT NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(timestamp, artist, album, track)
                );
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(albums)")}
            for name, kind in (("spotify_checked_at", "INTEGER"), ("spotify_checked_market", "TEXT"),
                               ("spotify_match_source", "TEXT"), ("release_year", "INTEGER")):
                if name not in columns:
                    conn.execute(f"ALTER TABLE albums ADD COLUMN {name} {kind}")
            if version < 2:
                conn.execute("""UPDATE albums SET release_year=(SELECT CAST(MIN(tag) AS INTEGER)
                    FROM album_tags WHERE album_id=albums.id AND tag GLOB '[12][0-9][0-9][0-9]'
                    HAVING COUNT(DISTINCT tag)=1) WHERE release_year IS NULL""")
                conn.execute("DELETE FROM album_tags WHERE tag GLOB '[12][0-9][0-9][0-9]'")
            conn.execute("PRAGMA user_version=2")
            previous_tz = self.get_state("timezone", conn)
            if previous_tz and previous_tz != tz:
                # Recalculate in batches so a large history is not loaded into memory.
                cursor = conn.execute("SELECT id, timestamp FROM scrobbles")
                while rows := cursor.fetchmany(1000):
                    conn.executemany(
                        "UPDATE scrobbles SET year=?, month=?, day_of_week=?, hour=? WHERE id=?",
                        [(*self.local_fields(row["timestamp"]), row["id"]) for row in rows],
                    )
            self.set_state("timezone", tz, conn)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def local_fields(self, timestamp):
        local = datetime.fromtimestamp(timestamp, self.tz)
        return local.year, local.month, local.isoweekday(), local.hour

    def get_state(self, key, conn=None):
        if conn is None:
            with self.connect() as conn:
                return self.get_state(key, conn)
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_state(self, key, value, conn=None):
        if conn is None:
            with self.connect() as conn:
                return self.set_state(key, value, conn)
        conn.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value)))

    def begin_import(self, upper):
        with self.connect() as conn:
            job = self.get_state("import", conn)
            if job:
                return job
            watermark = self.get_state("last_success_upper", conn)
            job = {"upper": upper, "lower": max(0, watermark - 172800) if watermark else 0,
                   "page": 1, "total_pages": None}
            conn.execute("DELETE FROM import_seen")
            self.set_state("import", job, conn)
            return job

    def save_page(self, tracks, job, total_pages):
        """Preserve source multiplicity even when equal events cross page boundaries."""
        counts = Counter((int(t["timestamp"]), t["artist"], t["album"], t["track"])
                         for t in tracks)
        metadata = {(int(t["timestamp"]), t["artist"], t["album"], t["track"]): t
                    for t in tracks}
        with self.connect() as conn:
            for key, count in counts.items():
                timestamp, artist, album, track = key
                seen = conn.execute("""SELECT count FROM import_seen
                    WHERE timestamp=? AND artist=? AND album=? AND track=?""", key).fetchone()
                old_count = seen[0] if seen else 0
                album_id = None
                if album.strip():
                    conn.execute("""INSERT OR IGNORE INTO albums
                        (artist, album, artist_search, album_search, mbid) VALUES (?, ?, ?, ?, ?)""",
                                 (artist, album, normalized(artist), normalized(album),
                                  metadata[key].get("album_mbid", "")))
                    album_id = conn.execute("SELECT id FROM albums WHERE artist=? AND album=?",
                                            (artist, album)).fetchone()[0]
                inserted = 0
                for occurrence in range(old_count + 1, old_count + count + 1):
                    result = conn.execute("""INSERT OR IGNORE INTO scrobbles
                        (timestamp, artist, album, track, track_mbid, album_id, occurrence,
                         year, month, day_of_week, hour) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (*key, metadata[key].get("track_mbid", ""), album_id, occurrence,
                         *self.local_fields(timestamp)))
                    inserted += result.rowcount
                if album_id and inserted:
                    conn.execute("""UPDATE albums SET scrobbles_total=scrobbles_total+?,
                        last_listened_at=MAX(COALESCE(last_listened_at, 0), ?) WHERE id=?""",
                                 (inserted, timestamp, album_id))
                conn.execute("INSERT OR REPLACE INTO import_seen VALUES (?, ?, ?, ?, ?)",
                             (*key, old_count + count))
            next_job = {**job, "page": job["page"] + 1, "total_pages": total_pages}
            self.set_state("import", next_job, conn)
            return next_job

    def finish_import(self, upper):
        with self.connect() as conn:
            self.set_state("last_success_upper", upper, conn)
            self.set_state("last_sync_at", int(time.time()), conn)
            self.set_state("import", None, conn)
            self.set_state("last_error", None, conn)
            conn.execute("DELETE FROM import_seen")

    def status(self):
        with self.connect() as conn:
            return {"scrobbles": conn.execute("SELECT COUNT(*) FROM scrobbles").fetchone()[0],
                    "albums": conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0],
                    "confirmed_albums": conn.execute(
                        "SELECT COUNT(*) FROM albums WHERE spotify_status='confirmed'").fetchone()[0],
                    "automatic_albums": conn.execute(
                        "SELECT COUNT(*) FROM albums WHERE spotify_match_source='automatic'").fetchone()[0],
                    "spotify_candidates": conn.execute(
                        "SELECT COUNT(*) FROM albums WHERE spotify_status='candidate'").fetchone()[0],
                    **{key: self.get_state(key, conn) for key in
                       ("last_sync_at", "last_error", "import", "enrichment_error", "spotify_error", "timezone")}}

    @staticmethod
    def album_result(conn, row):
        if row is None:
            return None
        result = dict(row)
        result["tags"] = [r[0] for r in conn.execute(
            "SELECT tag FROM album_tags WHERE album_id=? ORDER BY tag", (row["id"],))]
        return result

    def albums(self, limit=30, query=""):
        with self.connect() as conn:
            # instr treats user input literally rather than as LIKE wildcard syntax.
            rows = conn.execute("""SELECT * FROM albums
                WHERE instr(artist_search, ?) > 0 OR instr(album_search, ?) > 0
                ORDER BY scrobbles_total DESC, id LIMIT ?""",
                (normalized(query), normalized(query), limit)).fetchall()
            return [self.album_result(conn, row) for row in rows]

    def album(self, album_id):
        with self.connect() as conn:
            return self.album_result(conn, conn.execute("SELECT * FROM albums WHERE id=?", (album_id,)).fetchone())

    def recommend(self, min_years=3, min_scrobbles=10, genre="", playable_only=True):
        with self.connect() as conn:
            row = conn.execute("""SELECT a.* FROM albums a
                WHERE last_listened_at < ? AND scrobbles_total >= ?
                AND (? = 0 OR spotify_status='confirmed')
                AND (? = '' OR EXISTS (SELECT 1 FROM album_tags t
                    WHERE t.album_id=a.id AND t.tag=?))
                ORDER BY RANDOM() LIMIT 1""",
                (calendar_cutoff(min_years), min_scrobbles, int(playable_only),
                 normalized(genre), normalized(genre))).fetchone()
            result = self.album_result(conn, row)
            if result:
                result["reason"] = {"scrobbles_total": result["scrobbles_total"],
                                    "last_listened_at": result["last_listened_at"],
                                    "min_years_unheard": min_years}
            return result

    def genres(self, limit=200, now=None):
        """Rank tags by local listening period/hour without excluding other music."""
        local = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        if local.isoweekday() <= 4:
            weekdays, period = (1, 2, 3, 4), "Monday–Thursday"
        elif local.isoweekday() == 5:
            weekdays, period = (5,), "Friday"
        else:
            weekdays, period = (6, 7), "Weekend"
        # Keep Friday and weekend observations separate even near midnight.
        pairs = set()
        for day in weekdays:
            for offset in range(-2, 3):
                day_shift, hour = divmod(local.hour + offset, 24)
                shifted_day = (day - 1 + day_shift) % 7 + 1
                if shifted_day in weekdays:
                    pairs.add((shifted_day, hour))
        slots = [value for pair in sorted(pairs) for value in pair]
        where = " OR ".join(["(day_of_week=? AND hour=?)"] * len(pairs))
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(f"""WITH context AS (
                SELECT album_id, COUNT(*) AS listens FROM scrobbles
                WHERE {where} GROUP BY album_id
                ) SELECT t.tag AS name, COUNT(*) AS album_count,
                SUM(CASE WHEN a.spotify_status='confirmed' THEN 1 ELSE 0 END) AS playable_album_count,
                SUM(a.scrobbles_total) AS scrobbles_total,
                SUM(COALESCE(c.listens, 0)) AS context_scrobbles,
                SUM(CASE WHEN c.listens > 0 THEN 1 ELSE 0 END) AS context_album_count
                FROM album_tags t JOIN albums a ON a.id=t.album_id
                LEFT JOIN context c ON c.album_id=a.id
                WHERE t.tag != '' AND length(t.tag) <= 100
                GROUP BY t.tag ORDER BY album_count DESC, t.tag""", slots)]
            for row in rows:
                # Balance time-specific listening against a tag's overall size;
                # shrink tiny samples so one old scrobble cannot dominate.
                row["context_score"] = round(row["context_scrobbles"] / (row["scrobbles_total"] + 20) ** 0.5, 4)
            contextual = sorted((row for row in rows if row["context_scrobbles"] >= 3),
                                key=lambda row: (-row["context_score"], -row["context_scrobbles"], row["name"]))
            return {"genres": rows[:limit], "contextual_genres": contextual[:limit],
                    "total_genres": len(rows), "has_more": len(rows) > limit,
                    "context": {"weekday": ("Monday", "Tuesday", "Wednesday", "Thursday",
                                             "Friday", "Saturday", "Sunday")[local.weekday()], "hour": local.hour,
                                "period": period, "weekdays": list(weekdays),
                                "timezone": str(self.tz), "window_hours": 2,
                                "matching_genres": len(contextual)},
                    "tagged_albums": conn.execute(
                        "SELECT COUNT(DISTINCT album_id) FROM album_tags").fetchone()[0],
                    "total_albums": conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]}

    def confirm_album(self, album_id, uri, tags=None):
        uri = spotify_uri(uri)
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM albums WHERE id=?", (album_id,)).fetchone():
                raise LookupError("Album not found")
            conn.execute("UPDATE albums SET spotify_uri=?, spotify_status='confirmed', spotify_match_source='manual' WHERE id=?",
                         (uri, album_id))
            if tags is not None:
                tags, year, has_years = album_tags(tags)
                if has_years:
                    conn.execute("UPDATE albums SET release_year=? WHERE id=?", (year, album_id))
                conn.execute("DELETE FROM album_tags WHERE album_id=?", (album_id,))
                conn.executemany("INSERT OR IGNORE INTO album_tags VALUES (?, ?)",
                                 [(album_id, normalized(tag)) for tag in tags if tag.strip()])

    def enrichment_queue(self, limit):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("""SELECT * FROM albums
                WHERE enriched_at IS NULL OR enriched_at < ?
                ORDER BY enriched_at IS NOT NULL, scrobbles_total DESC, id LIMIT ?""",
                (int(time.time()) - 30 * 86400, limit))]

    def save_enrichment(self, album_id, tags, image, candidate):
        tags, year, has_years = album_tags(tags)
        encoded_candidate = json.dumps(candidate) if candidate else None
        with self.connect() as conn:
            conn.execute("""UPDATE albums SET image_url=COALESCE(?, image_url),
                release_year=CASE WHEN ? THEN ? ELSE release_year END,
                spotify_candidate=COALESCE(?, spotify_candidate), enriched_at=?, spotify_status=CASE
                WHEN spotify_status='confirmed' THEN 'confirmed'
                WHEN ? IS NULL THEN spotify_status ELSE 'candidate' END WHERE id=?""",
                (image, has_years, year, encoded_candidate, int(time.time()), encoded_candidate, album_id))
            conn.executemany("INSERT OR IGNORE INTO album_tags VALUES (?, ?)",
                             [(album_id, normalized(tag)) for tag in tags if tag.strip()])

    def spotify_queue(self, limit, market):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("""SELECT * FROM albums
                WHERE spotify_status != 'confirmed' AND (spotify_checked_at IS NULL
                    OR spotify_checked_at < ? OR spotify_checked_market IS NOT ?)
                ORDER BY spotify_checked_at IS NOT NULL, scrobbles_total DESC, id LIMIT ?""",
                (int(time.time()) - 30 * 86400, market, limit))]

    def save_spotify_match(self, album_id, candidate, market):
        automatic = bool(candidate and candidate.get("confidence") == "exact_unique")
        uri = spotify_uri(candidate["uri"]) if automatic else None
        with self.connect() as conn:
            # The user may have confirmed a link while the network search ran.
            conn.execute("""UPDATE albums SET spotify_candidate=?, spotify_checked_at=?,
                spotify_checked_market=?, spotify_uri=?, spotify_status=?, spotify_match_source=?,
                image_url=COALESCE(?, image_url) WHERE id=? AND spotify_status != 'confirmed'""",
                (json.dumps(candidate) if candidate else None, int(time.time()), market, uri,
                 "confirmed" if automatic else "candidate" if candidate else "missing",
                 "automatic" if automatic else None, candidate.get("image_url") if candidate else None, album_id))

    def backup(self, destination):
        with self.connect() as source:
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
            finally:
                target.close()

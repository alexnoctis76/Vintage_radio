"""SQLite database manager for the Vintage Radio Music Manager."""

from __future__ import annotations

import sqlite3
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .resource_paths import app_data_dir
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SongRecord:
    id: int
    original_filename: str
    file_path: str
    title: Optional[str]
    artist: Optional[str]
    duration: Optional[float]
    file_hash: Optional[str]
    file_size: Optional[int]
    format: Optional[str]
    sd_path: Optional[str]
    created_at: str
    modified_at: str


class DatabaseManager:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        backups_dir: Optional[Path] = None,
        auto_backup: bool = False,
        backup_retention: int = 10,
    ) -> None:
        root = app_data_dir()
        self.db_path = db_path or root / "radio_manager.db"
        self.backups_dir = backups_dir or root / "backups"
        self.auto_backup = auto_backup
        self.backup_retention = backup_retention

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._apply_migrations()

    def close(self) -> None:
        self.conn.close()

    def _apply_pragmas(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")

    def _apply_migrations(self) -> None:
        self._ensure_settings_table()
        current = self._get_schema_version()
        print(f"[DB] Current schema version: {current}")
        if current < 1:
            self._create_schema_v1()
            self._set_schema_version(1)
            current = 1
        if current < 2:
            self._migrate_to_v2()
            self._set_schema_version(2)
            current = 2
        if current < 3:
            print("[DB] Running migration to v3...")
            self._migrate_to_v3()
            self._set_schema_version(3)
            current = 3
            print("[DB] Migration to v3 complete")
        # Safety: ensure sort_order column exists even if version was already 3
        # (handles cases where version was bumped but ALTER TABLE didn't succeed)
        self._ensure_sort_order_columns()
        print(f"[DB] Schema version after migrations: {current}")

    def _ensure_settings_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()

    def _get_schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?;", ("schema_version",)
        ).fetchone()
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def _set_schema_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);",
            ("schema_version", str(version)),
        )
        self.conn.commit()

    def _create_schema_v1(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                title TEXT,
                artist TEXT,
                duration REAL,
                file_hash TEXT,
                file_size INTEGER,
                format TEXT,
                sd_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS album_songs (
                album_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                track_order INTEGER NOT NULL,
                PRIMARY KEY (album_id, song_id),
                UNIQUE (album_id, track_order),
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS playlist_songs (
                playlist_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                track_order INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, song_id),
                UNIQUE (playlist_id, track_order),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sd_mapping (
                song_id INTEGER PRIMARY KEY,
                folder_number INTEGER NOT NULL,
                track_number INTEGER NOT NULL,
                UNIQUE (folder_number, track_number),
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_songs_hash_size
                ON songs (file_hash, file_size);
            CREATE INDEX IF NOT EXISTS idx_songs_path
                ON songs (file_path);
            CREATE INDEX IF NOT EXISTS idx_album_songs_order
                ON album_songs (album_id, track_order);
            CREATE INDEX IF NOT EXISTS idx_playlist_songs_order
                ON playlist_songs (playlist_id, track_order);
            """
        )
        self.conn.commit()

    def _migrate_to_v2(self) -> None:
        columns = self.conn.execute("PRAGMA table_info(songs);").fetchall()
        if not any(column["name"] == "sd_path" for column in columns):
            self.conn.execute("ALTER TABLE songs ADD COLUMN sd_path TEXT;")
            self.conn.commit()

    def _migrate_to_v3(self) -> None:
        """Add sort_order column to albums and playlists for user-defined ordering."""
        for table in ("albums", "playlists"):
            columns = self.conn.execute(f"PRAGMA table_info({table});").fetchall()
            col_names = [col["name"] for col in columns]
            if "sort_order" not in col_names:
                print(f"[DB Migration v3] Adding sort_order column to {table}")
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN sort_order INTEGER DEFAULT 0;")
            else:
                print(f"[DB Migration v3] sort_order column already exists in {table}")
        self.conn.commit()
        # Initialize sort_order based on current alphabetical order
        for table in ("albums", "playlists"):
            rows = self.conn.execute(
                f"SELECT id FROM {table} ORDER BY name COLLATE NOCASE;"
            ).fetchall()
            for idx, row in enumerate(rows):
                self.conn.execute(
                    f"UPDATE {table} SET sort_order = ? WHERE id = ?;",
                    (idx, row["id"]),
                )
        self.conn.commit()
        print("[DB Migration v3] sort_order initialized for all albums and playlists")

    def _ensure_sort_order_columns(self) -> None:
        """Safety check: add sort_order column if missing (e.g. version was
        bumped but the ALTER TABLE never actually ran)."""
        for table in ("albums", "playlists"):
            columns = self.conn.execute(f"PRAGMA table_info({table});").fetchall()
            col_names = [col["name"] for col in columns]
            if "sort_order" not in col_names:
                print(f"[DB] sort_order column missing from {table}, adding now...")
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN sort_order INTEGER DEFAULT 0;"
                )
                # Initialize sort_order based on current alphabetical order
                rows = self.conn.execute(
                    f"SELECT id FROM {table} ORDER BY name COLLATE NOCASE;"
                ).fetchall()
                for idx, row in enumerate(rows):
                    self.conn.execute(
                        f"UPDATE {table} SET sort_order = ? WHERE id = ?;",
                        (idx, row["id"]),
                    )
                self.conn.commit()
                print(f"[DB] sort_order column added and initialized for {table}")

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?;", (key,)
        ).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);",
            (key, value),
        )
        self.conn.commit()

    def get_song_by_id(self, song_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM songs WHERE id = ?;", (song_id,)
        ).fetchone()

    def get_songs_by_ids(self, song_ids: Iterable[int]) -> List[sqlite3.Row]:
        ids = list(song_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return self.conn.execute(
            f"SELECT * FROM songs WHERE id IN ({placeholders});",
            ids,
        ).fetchall()

    def get_song_by_path(self, file_path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM songs WHERE file_path = ?;", (file_path,)
        ).fetchone()

    def get_song_by_hash_size(
        self, file_hash: str, file_size: int
    ) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM songs WHERE file_hash = ? AND file_size = ?;",
            (file_hash, file_size),
        ).fetchone()

    def list_songs(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM songs ORDER BY title COLLATE NOCASE;"
        ).fetchall()

    def list_albums(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM albums ORDER BY sort_order, name COLLATE NOCASE;"
        ).fetchall()

    def get_album_by_id(self, album_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM albums WHERE id = ?;", (album_id,)
        ).fetchone()

    def list_playlists(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM playlists ORDER BY sort_order, name COLLATE NOCASE;"
        ).fetchall()

    def get_playlist_by_id(self, playlist_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM playlists WHERE id = ?;", (playlist_id,)
        ).fetchone()

    def add_song(
        self,
        *,
        original_filename: str,
        file_path: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        duration: Optional[float] = None,
        file_hash: Optional[str] = None,
        file_size: Optional[int] = None,
        format: Optional[str] = None,
        sd_path: Optional[str] = None,
    ) -> int:
        existing = None
        if file_hash and file_size is not None:
            existing = self.get_song_by_hash_size(file_hash, file_size)
        if existing is None:
            existing = self.get_song_by_path(file_path)
        if existing is not None:
            # Update file_path if the caller provides a different (valid) one.
            # This fixes re-import on a different machine where hash matches
            # but the old path is from another computer.
            old_path = existing["file_path"]
            if file_path and file_path != old_path:
                from pathlib import Path as _P
                if _P(file_path).exists() and not _P(old_path).exists():
                    self.update_song(int(existing["id"]), {"file_path": file_path})
            return int(existing["id"])

        self.conn.execute(
            """
            INSERT INTO songs (
                original_filename,
                file_path,
                title,
                artist,
                duration,
                file_hash,
                file_size,
                format,
                sd_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                original_filename,
                file_path,
                title,
                artist,
                duration,
                file_hash,
                file_size,
                format,
                sd_path,
            ),
        )
        self.conn.commit()
        song_id = self.conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        self._maybe_backup()
        return int(song_id)

    def insert_song_with_id(self, song_row: sqlite3.Row) -> None:
        self.conn.execute(
            """
            INSERT INTO songs (
                id,
                original_filename,
                file_path,
                title,
                artist,
                duration,
                file_hash,
                file_size,
                format,
                sd_path,
                created_at,
                modified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                song_row["id"],
                song_row["original_filename"],
                song_row["file_path"],
                song_row["title"],
                song_row["artist"],
                song_row["duration"],
                song_row["file_hash"],
                song_row["file_size"],
                song_row["format"],
                song_row["sd_path"],
                song_row["created_at"],
                song_row["modified_at"],
            ),
        )
        self.conn.commit()

    def update_song(self, song_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        fields["modified_at"] = datetime.utcnow().isoformat()
        columns = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [song_id]
        self.conn.execute(f"UPDATE songs SET {columns} WHERE id = ?;", values)
        self.conn.commit()
        self._maybe_backup()

    def update_song_sd_path(self, song_id: int, sd_path: str) -> None:
        self.update_song(song_id, {"sd_path": sd_path})

    def delete_song(self, song_id: int) -> None:
        self.conn.execute("DELETE FROM songs WHERE id = ?;", (song_id,))
        self.conn.commit()
        self._maybe_backup()

    def create_album(self, name: str, description: Optional[str] = None) -> int:
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM albums;"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO albums (name, description, sort_order) VALUES (?, ?, ?);",
            (name, description, max_order + 1),
        )
        self.conn.commit()
        album_id = self.conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        self._maybe_backup()
        return int(album_id)

    def update_album(self, album_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        fields["modified_at"] = datetime.utcnow().isoformat()
        columns = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [album_id]
        self.conn.execute(f"UPDATE albums SET {columns} WHERE id = ?;", values)
        self.conn.commit()
        self._maybe_backup()

    def delete_album(self, album_id: int) -> None:
        self.conn.execute("DELETE FROM albums WHERE id = ?;", (album_id,))
        self.conn.commit()
        self._maybe_backup()

    def create_playlist(self, name: str, description: Optional[str] = None) -> int:
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM playlists;"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO playlists (name, description, sort_order) VALUES (?, ?, ?);",
            (name, description, max_order + 1),
        )
        self.conn.commit()
        playlist_id = self.conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        self._maybe_backup()
        return int(playlist_id)

    def update_playlist(self, playlist_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        fields["modified_at"] = datetime.utcnow().isoformat()
        columns = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [playlist_id]
        self.conn.execute(f"UPDATE playlists SET {columns} WHERE id = ?;", values)
        self.conn.commit()
        self._maybe_backup()

    def delete_playlist(self, playlist_id: int) -> None:
        self.conn.execute("DELETE FROM playlists WHERE id = ?;", (playlist_id,))
        self.conn.commit()
        self._maybe_backup()

    def update_album_order(self, album_ids: List[int]) -> None:
        """Persist the display order of albums.  *album_ids* is the ordered list."""
        with self.conn:
            for idx, aid in enumerate(album_ids):
                self.conn.execute(
                    "UPDATE albums SET sort_order = ? WHERE id = ?;", (idx, aid)
                )
        self.conn.commit()
        self._maybe_backup()

    def update_playlist_order(self, playlist_ids: List[int]) -> None:
        """Persist the display order of playlists.  *playlist_ids* is the ordered list."""
        with self.conn:
            for idx, pid in enumerate(playlist_ids):
                self.conn.execute(
                    "UPDATE playlists SET sort_order = ? WHERE id = ?;", (idx, pid)
                )
        self.conn.commit()
        self._maybe_backup()

    def add_song_to_album(self, album_id: int, song_id: int, track_order: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM album_songs WHERE album_id = ? AND track_order = ?;",
                (album_id, track_order),
            )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO album_songs (album_id, song_id, track_order)
                VALUES (?, ?, ?);
                """,
                (album_id, song_id, track_order),
            )
        self._maybe_backup()

    def remove_song_from_album(self, album_id: int, song_id: int) -> None:
        self.conn.execute(
            "DELETE FROM album_songs WHERE album_id = ? AND song_id = ?;",
            (album_id, song_id),
        )
        self.conn.commit()
        self._maybe_backup()

    def list_album_songs(self, album_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT songs.*
            FROM album_songs
            JOIN songs ON songs.id = album_songs.song_id
            WHERE album_songs.album_id = ?
            ORDER BY album_songs.track_order ASC;
            """,
            (album_id,),
        ).fetchall()

    def list_album_tracks(self, album_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT song_id, track_order
            FROM album_songs
            WHERE album_id = ?
            ORDER BY track_order ASC;
            """,
            (album_id,),
        ).fetchall()

    def insert_album_track(
        self, album_id: int, song_id: int, track_order: int
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO album_songs (album_id, song_id, track_order)
            VALUES (?, ?, ?);
            """,
            (album_id, song_id, track_order),
        )
        self.conn.commit()

    def replace_album_tracks(self, album_id: int, song_ids: Iterable[int]) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM album_songs WHERE album_id = ?;", (album_id,)
            )
            for index, song_id in enumerate(song_ids, start=1):
                self.conn.execute(
                    """
                    INSERT INTO album_songs (album_id, song_id, track_order)
                    VALUES (?, ?, ?);
                    """,
                    (album_id, song_id, index),
                )
        self._maybe_backup()

    def next_album_track_order(self, album_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(track_order), 0) AS max_order FROM album_songs WHERE album_id = ?;",
            (album_id,),
        ).fetchone()
        return int(row["max_order"]) + 1

    def add_song_to_playlist(
        self, playlist_id: int, song_id: int, track_order: int
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM playlist_songs WHERE playlist_id = ? AND track_order = ?;",
                (playlist_id, track_order),
            )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO playlist_songs (playlist_id, song_id, track_order)
                VALUES (?, ?, ?);
                """,
                (playlist_id, song_id, track_order),
            )
        self._maybe_backup()

    def remove_song_from_playlist(self, playlist_id: int, song_id: int) -> None:
        self.conn.execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ? AND song_id = ?;",
            (playlist_id, song_id),
        )
        self.conn.commit()
        self._maybe_backup()

    def list_playlist_songs(self, playlist_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT songs.*
            FROM playlist_songs
            JOIN songs ON songs.id = playlist_songs.song_id
            WHERE playlist_songs.playlist_id = ?
            ORDER BY playlist_songs.track_order ASC;
            """,
            (playlist_id,),
        ).fetchall()

    def list_playlist_tracks(self, playlist_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT song_id, track_order
            FROM playlist_songs
            WHERE playlist_id = ?
            ORDER BY track_order ASC;
            """,
            (playlist_id,),
        ).fetchall()

    def insert_playlist_track(
        self, playlist_id: int, song_id: int, track_order: int
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id, track_order)
            VALUES (?, ?, ?);
            """,
            (playlist_id, song_id, track_order),
        )
        self.conn.commit()

    def replace_playlist_tracks(
        self, playlist_id: int, song_ids: Iterable[int]
    ) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM playlist_songs WHERE playlist_id = ?;", (playlist_id,)
            )
            for index, song_id in enumerate(song_ids, start=1):
                self.conn.execute(
                    """
                    INSERT INTO playlist_songs (playlist_id, song_id, track_order)
                    VALUES (?, ?, ?);
                    """,
                    (playlist_id, song_id, index),
                )
        self._maybe_backup()

    def next_playlist_track_order(self, playlist_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(track_order), 0) AS max_order FROM playlist_songs WHERE playlist_id = ?;",
            (playlist_id,),
        ).fetchone()
        return int(row["max_order"]) + 1

    def set_sd_mapping(self, song_id: int, folder_number: int, track_number: int) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO sd_mapping (song_id, folder_number, track_number)
            VALUES (?, ?, ?);
            """,
            (song_id, folder_number, track_number),
        )
        self.conn.commit()
        self._maybe_backup()

    def get_sd_mapping(self, song_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sd_mapping WHERE song_id = ?;", (song_id,)
        ).fetchone()

    def backup_now(self) -> Optional[Path]:
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backups_dir / f"radio_manager_{timestamp}.db"
        shutil.copy2(self.db_path, backup_path)
        self._enforce_backup_retention()
        return backup_path

    def restore_from_backup(self, backup_path: Path) -> None:
        shutil.copy2(backup_path, self.db_path)

    def _maybe_backup(self) -> None:
        if self.auto_backup:
            self.backup_now()

    def _enforce_backup_retention(self) -> None:
        if self.backup_retention <= 0:
            return
        backups = sorted(
            self.backups_dir.glob("radio_manager_*.db"),
            key=lambda p: p.stat().st_mtime,
        )
        if len(backups) <= self.backup_retention:
            return
        for path in backups[: len(backups) - self.backup_retention]:
            path.unlink(missing_ok=True)



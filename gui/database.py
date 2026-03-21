"""SQLite database manager for the Vintage Radio Music Manager."""

from __future__ import annotations

import sqlite3
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .resource_paths import app_data_dir
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 6


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
        if current < 4:
            print("[DB] Running migration to v4...")
            self._migrate_to_v4()
            self._set_schema_version(4)
            current = 4
            print("[DB] Migration to v4 complete")
        if current < 5:
            print("[DB] Running migration to v5...")
            self._migrate_to_v5()
            self._set_schema_version(5)
            current = 5
            print("[DB] Migration to v5 complete")
        if current < 6:
            print("[DB] Running migration to v6...")
            self._migrate_to_v6()
            self._set_schema_version(6)
            current = 6
            print("[DB] Migration to v6 complete")
        # Safety: ensure sort_order column exists even if version was already 3
        # (handles cases where version was bumped but ALTER TABLE didn't succeed)
        self._ensure_sort_order_columns()
        self._ensure_device_profiles_table()
        self._ensure_basic_stations_tables()
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

    def _migrate_to_v4(self) -> None:
        """Add device_profiles table for configurable pin layouts and board selection."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                notes TEXT DEFAULT '',
                board_id TEXT NOT NULL DEFAULT 'raspberry_pi_pico',
                pin_config_json TEXT NOT NULL DEFAULT '{}',
                custom_hw_driver_path TEXT DEFAULT '',
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.commit()
        self._ensure_default_device_profile()

    def _ensure_device_profiles_table(self) -> None:
        """Safety: create device_profiles table and default profile if missing."""
        tables = [
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        ]
        if "device_profiles" not in tables:
            self._migrate_to_v4()
        else:
            self._ensure_default_device_profile()

    def _migrate_to_v5(self) -> None:
        """Add basic_stations and basic_station_tracks tables for basic-mode station management."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS basic_stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                folder_number INTEGER NOT NULL UNIQUE,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS basic_station_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                track_order INTEGER NOT NULL,
                UNIQUE (station_id, track_order),
                FOREIGN KEY (station_id) REFERENCES basic_stations(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_basic_station_tracks_order
                ON basic_station_tracks (station_id, track_order);
            """
        )
        self.conn.commit()

    def _migrate_to_v6(self) -> None:
        """Recreate basic_station_tracks with auto-increment PK (allows duplicate songs per station)."""
        tables = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        if "basic_station_tracks" not in tables:
            return
        # Check if old schema has (station_id, song_id) as PK by inspecting columns
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(basic_station_tracks);").fetchall()]
        if "id" in cols:
            return  # Already migrated
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS basic_station_tracks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                song_id INTEGER NOT NULL,
                track_order INTEGER NOT NULL,
                UNIQUE (station_id, track_order),
                FOREIGN KEY (station_id) REFERENCES basic_stations(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
            );
            INSERT INTO basic_station_tracks_new (station_id, song_id, track_order)
                SELECT station_id, song_id, track_order FROM basic_station_tracks;
            DROP TABLE basic_station_tracks;
            ALTER TABLE basic_station_tracks_new RENAME TO basic_station_tracks;
            CREATE INDEX IF NOT EXISTS idx_basic_station_tracks_order
                ON basic_station_tracks (station_id, track_order);
            """
        )
        self.conn.commit()

    def _ensure_basic_stations_tables(self) -> None:
        """Safety: create basic_stations tables if missing."""
        tables = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        if "basic_stations" not in tables or "basic_station_tracks" not in tables:
            self._migrate_to_v5()

    def _ensure_default_device_profile(self) -> None:
        """Ensure at least one default profile exists."""
        row = self.conn.execute(
            "SELECT id FROM device_profiles WHERE is_default = 1;"
        ).fetchone()
        if row is None:
            count = self.conn.execute("SELECT COUNT(*) as c FROM device_profiles;").fetchone()["c"]
            if count == 0:
                from .board_profiles import get_default_board_profile
                bp = get_default_board_profile()
                now = datetime.now(timezone.utc).isoformat()
                self.conn.execute(
                    """INSERT INTO device_profiles
                       (name, notes, board_id, pin_config_json, custom_hw_driver_path, is_default, created_at, modified_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?);""",
                    ("Default (Pico)", "", bp.id, bp.default_config_json(), "", now, now),
                )
                self.conn.commit()
                new_id = self.conn.execute("SELECT last_insert_rowid();").fetchone()[0]
                self.set_setting("active_profile_id", str(new_id))

    # ---- Device Profile CRUD ----

    def create_device_profile(
        self,
        name: str,
        board_id: str,
        pin_config_json: str,
        notes: str = "",
        custom_hw_driver_path: str = "",
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            """INSERT INTO device_profiles
               (name, notes, board_id, pin_config_json, custom_hw_driver_path, is_default, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?);""",
            (name, notes, board_id, pin_config_json, custom_hw_driver_path, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_device_profile(self, profile_id: int, **fields) -> None:
        allowed = {"name", "notes", "board_id", "pin_config_json", "custom_hw_driver_path"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["modified_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [profile_id]
        self.conn.execute(
            f"UPDATE device_profiles SET {set_clause} WHERE id = ?;",
            values,
        )
        self.conn.commit()

    def delete_device_profile(self, profile_id: int) -> bool:
        row = self.conn.execute(
            "SELECT is_default FROM device_profiles WHERE id = ?;", (profile_id,)
        ).fetchone()
        if row is None or row["is_default"] == 1:
            return False
        count = self.conn.execute("SELECT COUNT(*) as c FROM device_profiles;").fetchone()["c"]
        if count <= 1:
            return False
        self.conn.execute("DELETE FROM device_profiles WHERE id = ?;", (profile_id,))
        self.conn.commit()
        active = self.get_setting("active_profile_id")
        if active == str(profile_id):
            first = self.conn.execute("SELECT id FROM device_profiles ORDER BY id LIMIT 1;").fetchone()
            if first:
                self.set_setting("active_profile_id", str(first["id"]))
        return True

    def duplicate_device_profile(self, profile_id: int, new_name: str) -> int:
        row = self.get_device_profile(profile_id)
        if row is None:
            raise ValueError(f"Profile {profile_id} not found")
        return self.create_device_profile(
            name=new_name,
            board_id=row["board_id"],
            pin_config_json=row["pin_config_json"],
            notes=row["notes"],
            custom_hw_driver_path=row["custom_hw_driver_path"],
        )

    def get_device_profile(self, profile_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM device_profiles WHERE id = ?;", (profile_id,)
        ).fetchone()

    def list_device_profiles(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM device_profiles ORDER BY is_default DESC, name COLLATE NOCASE;"
        ).fetchall()

    def get_active_profile(self) -> Optional[sqlite3.Row]:
        pid = self.get_setting("active_profile_id")
        if pid is not None:
            row = self.get_device_profile(int(pid))
            if row is not None:
                return row
        first = self.conn.execute(
            "SELECT * FROM device_profiles ORDER BY is_default DESC, id LIMIT 1;"
        ).fetchone()
        if first:
            self.set_setting("active_profile_id", str(first["id"]))
        return first

    def set_active_profile(self, profile_id: int) -> None:
        self.set_setting("active_profile_id", str(profile_id))

    # ---- Basic Station CRUD ----

    def create_basic_station(self, name: str, folder_number: int) -> int:
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM basic_stations;"
        ).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO basic_stations (name, folder_number, sort_order, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?);""",
            (name, folder_number, max_order + 1, now, now),
        )
        self.conn.commit()
        station_id = self.conn.execute("SELECT last_insert_rowid();").fetchone()[0]
        self._maybe_backup()
        return int(station_id)

    def update_basic_station(self, station_id: int, **fields) -> None:
        allowed = {"name", "folder_number"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["modified_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [station_id]
        self.conn.execute(
            f"UPDATE basic_stations SET {set_clause} WHERE id = ?;", values
        )
        self.conn.commit()
        self._maybe_backup()

    def delete_basic_station(self, station_id: int) -> None:
        self.conn.execute("DELETE FROM basic_stations WHERE id = ?;", (station_id,))
        self.conn.commit()
        self._maybe_backup()

    def get_basic_station(self, station_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM basic_stations WHERE id = ?;", (station_id,)
        ).fetchone()

    def list_basic_stations(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM basic_stations ORDER BY sort_order, folder_number;"
        ).fetchall()

    def next_basic_station_folder(self) -> int:
        """Return the next unused DFPlayer folder number (1-98)."""
        used = {
            r["folder_number"]
            for r in self.conn.execute("SELECT folder_number FROM basic_stations;").fetchall()
        }
        for n in range(1, 99):
            if n not in used:
                return n
        raise ValueError("All 98 DFPlayer folders are in use")

    def update_basic_station_order(self, station_ids: List[int]) -> None:
        """Reorder stations and reassign folder numbers so position matches folder (1-indexed)."""
        with self.conn:
            # Temporarily set folder_number to negative to avoid UNIQUE conflicts during swap
            for idx, sid in enumerate(station_ids):
                self.conn.execute(
                    "UPDATE basic_stations SET sort_order = ?, folder_number = ? WHERE id = ?;",
                    (idx, -(idx + 1), sid),
                )
            for idx, sid in enumerate(station_ids):
                self.conn.execute(
                    "UPDATE basic_stations SET folder_number = ? WHERE id = ?;",
                    (idx + 1, sid),
                )
        self.conn.commit()
        self._maybe_backup()

    def add_song_to_basic_station(self, station_id: int, song_id: int, track_order: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM basic_station_tracks WHERE station_id = ? AND track_order = ?;",
                (station_id, track_order),
            )
            self.conn.execute(
                """INSERT INTO basic_station_tracks (station_id, song_id, track_order)
                   VALUES (?, ?, ?);""",
                (station_id, song_id, track_order),
            )
        self._maybe_backup()

    def remove_basic_station_track(self, track_row_id: int) -> None:
        """Remove a single track entry by its row id (allows removing one instance of a duplicate)."""
        self.conn.execute(
            "DELETE FROM basic_station_tracks WHERE id = ?;", (track_row_id,)
        )
        self.conn.commit()
        self._maybe_backup()

    def remove_song_from_basic_station(self, station_id: int, song_id: int) -> None:
        """Remove all instances of a song from a station."""
        self.conn.execute(
            "DELETE FROM basic_station_tracks WHERE station_id = ? AND song_id = ?;",
            (station_id, song_id),
        )
        self.conn.commit()
        self._maybe_backup()

    def list_basic_station_songs(self, station_id: int) -> List[sqlite3.Row]:
        """Return all tracks for a station, including duplicates. Each row has a
        ``bst_id`` column (the basic_station_tracks row id) for individual removal."""
        return self.conn.execute(
            """SELECT basic_station_tracks.id AS bst_id, songs.*
               FROM basic_station_tracks
               JOIN songs ON songs.id = basic_station_tracks.song_id
               WHERE basic_station_tracks.station_id = ?
               ORDER BY basic_station_tracks.track_order ASC;""",
            (station_id,),
        ).fetchall()

    def list_basic_station_tracks(self, station_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            """SELECT id, song_id, track_order
               FROM basic_station_tracks
               WHERE station_id = ?
               ORDER BY track_order ASC;""",
            (station_id,),
        ).fetchall()

    def replace_basic_station_tracks(self, station_id: int, song_ids: Iterable[int]) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM basic_station_tracks WHERE station_id = ?;", (station_id,)
            )
            for index, song_id in enumerate(song_ids, start=1):
                self.conn.execute(
                    """INSERT INTO basic_station_tracks (station_id, song_id, track_order)
                       VALUES (?, ?, ?);""",
                    (station_id, song_id, index),
                )
        self._maybe_backup()

    def next_basic_station_track_order(self, station_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(track_order), 0) AS max_order FROM basic_station_tracks WHERE station_id = ?;",
            (station_id,),
        ).fetchone()
        return int(row["max_order"]) + 1

    def clear_all_basic_stations(self) -> None:
        """Remove all basic stations and their track associations."""
        with self.conn:
            self.conn.execute("DELETE FROM basic_station_tracks;")
            self.conn.execute("DELETE FROM basic_stations;")
        self.conn.commit()
        self._maybe_backup()

    # ---- Settings ----

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
        fields["modified_at"] = datetime.now(timezone.utc).isoformat()
        columns = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [song_id]
        self.conn.execute(f"UPDATE songs SET {columns} WHERE id = ?;", values)
        self.conn.commit()
        self._maybe_backup()

    def update_song_sd_path(self, song_id: int, sd_path: Optional[str]) -> None:
        path_str = "" if sd_path is None else str(sd_path)
        self.update_song(song_id, {"sd_path": path_str})

    def update_song_sd_paths_batch(self, updates: List[tuple]) -> None:
        """Update sd_path and modified_at for many songs in one transaction. items: [(song_id, sd_path), ...]."""
        if not updates:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = [(path_str if path_str is not None else "", now, song_id) for song_id, path_str in updates]
        self.conn.executemany(
            "UPDATE songs SET sd_path = ?, modified_at = ? WHERE id = ?;",
            rows,
        )
        self.conn.commit()
        self._maybe_backup()

    def set_sd_mappings_batch(self, mappings: List[tuple]) -> None:
        """Insert/replace many sd_mapping rows in one transaction. items: [(song_id, folder_number, track_number), ...]."""
        if not mappings:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO sd_mapping (song_id, folder_number, track_number) VALUES (?, ?, ?);",
            mappings,
        )
        self.conn.commit()
        self._maybe_backup()

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
        fields["modified_at"] = datetime.now(timezone.utc).isoformat()
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
        fields["modified_at"] = datetime.now(timezone.utc).isoformat()
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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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



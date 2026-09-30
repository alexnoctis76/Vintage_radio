"""Tests for gui.library_manager.LibraryRegistry."""

import json

import pytest

from gui.library_manager import LibraryRegistry


@pytest.fixture
def registry(tmp_path):
    return LibraryRegistry(root=tmp_path)


class TestInit:
    def test_creates_default_library(self, registry, tmp_path):
        reg_file = tmp_path / "libraries" / "libraries.json"
        assert reg_file.exists()
        data = json.loads(reg_file.read_text())
        assert "default" in data["libraries"]
        assert data["active"] == "default"

    def test_list_libraries_has_default(self, registry):
        libs = registry.list_libraries()
        assert len(libs) == 1
        assert libs[0]["slug"] == "default"
        assert libs[0]["is_active"] is True


class TestCreateLibrary:
    def test_creates_new(self, registry):
        slug = registry.create_library("Rock Collection")
        assert slug == "rock-collection"
        libs = registry.list_libraries()
        names = {lib["name"] for lib in libs}
        assert "Rock Collection" in names

    def test_duplicate_name_gets_unique_slug(self, registry):
        slug1 = registry.create_library("Dupe")
        slug2 = registry.create_library("Dupe")
        assert slug1 != slug2
        assert slug2.startswith("dupe")

    def test_unique_slug_on_collision(self, registry):
        slug1 = registry.create_library("Jazz")
        slug2 = registry.create_library("Jazz 2")
        assert slug1 != slug2


class TestRenameLibrary:
    def test_rename(self, registry):
        slug = registry.create_library("Old Name")
        registry.rename_library(slug, "New Name")
        libs = {lib["slug"]: lib for lib in registry.list_libraries()}
        assert libs[slug]["name"] == "New Name"

    def test_rename_unknown_raises(self, registry):
        with pytest.raises(KeyError):
            registry.rename_library("nonexistent", "X")


class TestDeleteLibrary:
    def test_delete_non_active(self, registry):
        slug = registry.create_library("Temp")
        registry.delete_library(slug)
        slugs = {lib["slug"] for lib in registry.list_libraries()}
        assert slug not in slugs

    def test_delete_last_library_raises(self, registry):
        with pytest.raises(RuntimeError):
            registry.delete_library("default")

    def test_delete_active_switches(self, registry):
        slug = registry.create_library("Other")
        registry.set_active(slug)
        registry.delete_library(slug)
        assert registry.active_library() == "default"

    def test_unknown_slug_raises(self, registry):
        with pytest.raises(KeyError):
            registry.delete_library("bogus")


class TestSetActive:
    def test_switch_active(self, registry):
        slug = registry.create_library("Alt")
        registry.set_active(slug)
        assert registry.active_library() == slug

    def test_unknown_raises(self, registry):
        with pytest.raises(KeyError):
            registry.set_active("nope")


class TestDuplicateAndFamily:
    def test_duplicate_copies_db_and_metadata(self, registry, tmp_path):
        slug = registry.create_library("Jazz Nights")
        db_path = registry.db_path_for(slug)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"sqlite-placeholder")
        registry.set_library_firmware_family(slug, "conductor")
        registry.set_library_commercials(slug, enabled=True, mode="inline")

        new_slug = registry.duplicate_library(slug)
        libs = {lib["slug"]: lib for lib in registry.list_libraries()}
        assert libs[new_slug]["name"] == "Jazz Nights (copy)"
        assert libs[slug]["name"] == "Jazz Nights"
        assert libs[new_slug]["firmware_family"] == "conductor"
        assert libs[new_slug]["commercials_enabled"] is True
        assert libs[new_slug]["commercials_mode"] == "inline"
        assert registry.db_path_for(new_slug).read_bytes() == b"sqlite-placeholder"
        assert registry.db_path_for(slug).read_bytes() == b"sqlite-placeholder"

    def test_both_commercials_mode_persists(self, registry):
        slug = registry.create_library("Mix")
        registry.set_library_firmware_family(slug, "conductor")
        registry.set_library_commercials(slug, enabled=True, mode="both")
        info = registry.library_meta(slug)
        assert info["commercials_mode"] == "both"
        assert info["firmware_family"] == "conductor"

    def test_default_library_is_basic_without_commercials(self, registry):
        info = registry.library_meta("default")
        assert info["firmware_family"] == "basic"
        assert info["commercials_enabled"] is False

    def test_stale_conductor_family_reconciled_for_folder_commercials(self, registry):
        slug = registry.create_library("Commercials Test")
        registry.set_library_firmware_family(slug, "conductor")
        registry.set_library_commercials(slug, enabled=True, mode="folder_99")
        info = registry.library_meta(slug)
        assert info["firmware_family"] == "basic"
        assert info["commercials_mode"] == "folder_99"


class TestDbPathFor:
    def test_default_path(self, registry, tmp_path):
        path = registry.db_path_for("default")
        assert path == tmp_path / "radio_manager.db"

    def test_created_library_path(self, registry, tmp_path):
        slug = registry.create_library("Custom")
        path = registry.db_path_for(slug)
        assert path == tmp_path / "libraries" / f"{slug}.db"

    def test_unknown_raises(self, registry):
        with pytest.raises(KeyError):
            registry.db_path_for("???")

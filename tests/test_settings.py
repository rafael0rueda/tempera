# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from tempera import settings


def use_tmp_settings_file(monkeypatch, tmp_path):
    path = tmp_path / "tempera" / "settings.ini"
    monkeypatch.setattr(settings, "_settings_path", lambda: path)
    return path


def test_palette_defaults_to_the_right(monkeypatch, tmp_path):
    use_tmp_settings_file(monkeypatch, tmp_path)
    assert settings.load_palette_position() == "right"


def test_palette_position_round_trips(monkeypatch, tmp_path):
    use_tmp_settings_file(monkeypatch, tmp_path)
    settings.save_palette_position("left")
    assert settings.load_palette_position() == "left"


def test_unknown_palette_position_falls_back_to_the_default(monkeypatch, tmp_path):
    path = use_tmp_settings_file(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text("[view]\npalette-position = top\n", encoding="utf-8")
    assert settings.load_palette_position() == "right"


def test_damaged_settings_file_falls_back_to_the_default(monkeypatch, tmp_path):
    path = use_tmp_settings_file(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text("not an ini file", encoding="utf-8")
    assert settings.load_palette_position() == "right"
    settings.save_palette_position("left")
    assert settings.load_palette_position() == "left"


def test_unwritable_config_directory_is_not_an_error(monkeypatch, tmp_path):
    blocker = tmp_path / "tempera"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    use_tmp_settings_file(monkeypatch, tmp_path)
    settings.save_palette_position("left")
    assert settings.load_palette_position() == "right"


def test_old_hue_settings_are_carried_over_once(tmp_path):
    old = tmp_path / settings.OLD_CONFIG_NAME
    old.mkdir()
    (old / "settings.ini").write_text("[view]\npalette-position = left\n", encoding="utf-8")
    (old / "recent-files.txt").write_text("file:///a.png\n", encoding="utf-8")

    settings.migrate_old_config(tmp_path)

    new = tmp_path / settings.CONFIG_NAME
    assert (new / "settings.ini").read_text(encoding="utf-8").endswith("left\n")
    assert (new / "recent-files.txt").read_text(encoding="utf-8") == "file:///a.png\n"
    assert (old / "settings.ini").exists()
    assert not (tmp_path / (settings.CONFIG_NAME + ".tmp")).exists()


def test_migration_never_overwrites_tempera_settings(tmp_path):
    old = tmp_path / settings.OLD_CONFIG_NAME
    old.mkdir()
    (old / "settings.ini").write_text("[view]\npalette-position = left\n", encoding="utf-8")
    new = tmp_path / settings.CONFIG_NAME
    new.mkdir()
    (new / "settings.ini").write_text("[view]\npalette-position = right\n", encoding="utf-8")

    settings.migrate_old_config(tmp_path)

    assert (new / "settings.ini").read_text(encoding="utf-8").endswith("right\n")


def test_migration_without_old_settings_creates_nothing(tmp_path):
    settings.migrate_old_config(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_settings_are_read_from_disk_once_while_unchanged(monkeypatch, tmp_path):
    use_tmp_settings_file(monkeypatch, tmp_path)
    settings.save_settings({"tool": "brush", "font": "Sans 12"})
    reads = []
    real_read_text = settings.Path.read_text
    monkeypatch.setattr(
        settings.Path,
        "read_text",
        lambda self, *args, **kwargs: reads.append(self) or real_read_text(self, *args, **kwargs),
    )
    for _round in range(5):
        assert settings.load_setting("tool") == "brush"
        assert settings.load_setting("font") == "Sans 12"
    assert reads == []


def test_a_change_made_by_another_window_is_noticed(monkeypatch, tmp_path):
    path = use_tmp_settings_file(monkeypatch, tmp_path)
    settings.save_settings({"tool": "brush"})
    assert settings.load_setting("tool") == "brush"
    path.write_text("[view]\ntool = rectangle\n", encoding="utf-8")
    assert settings.load_setting("tool") == "rectangle"


def test_saving_one_setting_leaves_the_cached_others_alone(monkeypatch, tmp_path):
    use_tmp_settings_file(monkeypatch, tmp_path)
    settings.save_settings({"tool": "brush"})
    settings.save_shortcut_overrides({"win.undo": ["<Control>u"]})
    settings.save_settings({"font": "Serif 9"})
    assert settings.load_setting("tool") == "brush"
    assert settings.load_shortcut_overrides() == {"win.undo": ["<Control>u"]}
    # What a caller gets back is its own to change.
    settings.load_shortcut_overrides()["win.undo"].append("<Control>q")
    assert settings.load_shortcut_overrides() == {"win.undo": ["<Control>u"]}

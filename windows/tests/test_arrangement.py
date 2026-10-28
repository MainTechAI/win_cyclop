"""Rearranging the panel tabs, and the version shown in Settings."""
from PySide6.QtCore import Qt

from cyclop_windows import __version__
from cyclop_windows.app import Panel
from cyclop_windows.core import ALL_TABS, DEFAULT_LEFT, DEFAULT_RIGHT, normalise_config, normalise_layout
from cyclop_windows.model import Model


def test_layout_is_repaired_and_settings_stays_last():
    assert normalise_layout(None) == {"left": DEFAULT_LEFT, "right": DEFAULT_RIGHT}
    layout = normalise_layout({"left": ["settings", "notes", "notes", "bogus", 7], "right": ["music"]})
    assert layout["left"][0] == "notes" and "settings" not in layout["left"]
    assert layout["right"][0] == "music" and layout["right"][-1] == "settings"
    assert sorted(layout["left"] + layout["right"]) == sorted(ALL_TABS)
    config = normalise_config({"disabled_tabs": ["settings", "shelf", "nope"]})
    assert config["disabled_tabs"] == ["shelf"], "Settings can never be hidden"


def make_panel(app, tmp_path):
    model = Model(tmp_path)
    panel = Panel(model, start_services=False)
    panel.watcher.stop()
    panel.show()
    panel.set_expanded(True)
    return model, panel


def rail_keys(panel, side):
    rail = panel.rails[side]
    return [rail.itemAt(i).widget().key for i in range(rail.count()) if rail.itemAt(i).widget()]


def test_rearranging_in_settings_moves_rail_buttons_and_cycling(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        arrangement = panel.panes["settings"].arrangement
        assert rail_keys(panel, "left") == DEFAULT_LEFT
        # Move "translate" (last on the left) below the divider: it joins the right rail.
        arrangement.select("translate")
        arrangement.move(1)
        assert model.config["tab_layout"]["right"][0] == "translate"
        assert rail_keys(panel, "right")[0] == "translate"
        assert rail_keys(panel, "left") == DEFAULT_LEFT[:-1]
        # Move "notes" to the very top.
        arrangement.select("notes")
        for _ in range(10):
            arrangement.move(-1)
        assert model.config["tab_layout"]["left"][0] == "notes"
        panel.select_tab(panel.tab_order()[-1])
        panel.cycle_tab(1)
        assert panel.current_tab == "notes", "cycling follows the user's order"
        # Settings cannot be moved, and nothing can be moved below it.
        arrangement.select("settings")
        arrangement.move(-1)
        assert model.config["tab_layout"]["right"][-1] == "settings"
        assert not arrangement.up.isEnabled() and not arrangement.down.isEnabled()
        arrangement.reset()
        assert model.config["tab_layout"] == {"left": DEFAULT_LEFT, "right": DEFAULT_RIGHT}
        assert rail_keys(panel, "left") == DEFAULT_LEFT
    finally:
        panel.shutdown()
        panel.close()


def test_drag_and_drop_order_is_saved(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        arrangement = panel.panes["settings"].arrangement
        widget = arrangement.list
        # What a drag does to the list model: take a row and insert it elsewhere.
        source = arrangement.order().index("music")
        item = widget.takeItem(source)
        widget.insertItem(arrangement.order().index(arrangement.DIVIDER) + 1, item)
        arrangement.apply()
        assert model.config["tab_layout"]["right"][0] == "music"
        assert "music" not in model.config["tab_layout"]["left"]
    finally:
        panel.shutdown()
        panel.close()


def test_unticking_hides_a_tab_and_a_long_rail_still_fits(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        arrangement = panel.panes["settings"].arrangement
        index = arrangement.order().index("currency")
        arrangement.list.item(index).setCheckState(Qt.CheckState.Unchecked)
        assert "currency" in model.config["disabled_tabs"]
        assert not panel.buttons["currency"].isVisible()
        # Everything on one rail: the panel grows so no icon is cut off.
        model.configure("disabled_tabs", [])
        model.configure("tab_layout", {"left": [key for key in ALL_TABS if key != "settings"], "right": []})
        panel.select_tab("shelf")
        panel.reposition()
        needed = 34 + 11 * 32 + 26
        assert panel.target_rect().height() >= min(needed, panel.display().availableGeometry().height())
    finally:
        panel.shutdown()
        panel.close()


def test_version_is_shown_at_the_bottom_of_settings(app, tmp_path):
    model, panel = make_panel(app, tmp_path)
    try:
        settings = panel.panes["settings"]
        assert settings.version.text() == f"Cyclop for Windows {__version__}"
        content = settings.content
        last_row = content.itemAt(content.count() - 1).layout()
        assert last_row is not None and last_row.itemAt(0).widget() is settings.version
    finally:
        panel.shutdown()
        panel.close()

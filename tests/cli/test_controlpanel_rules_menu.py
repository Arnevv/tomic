from __future__ import annotations

from tomic.cli.settings import handlers
from tomic.cli.settings.menu_config import SettingAction, SettingMenu, SETTINGS_MENU


def _find_menu(menu: SettingMenu, label: str) -> SettingMenu:
    for item in menu.items:
        if isinstance(item, SettingMenu) and item.label == label:
            return item
    raise AssertionError(f"Menu with label '{label}' not found")


def test_strategy_criteria_menu_contains_items() -> None:
    strategy_menu = _find_menu(SETTINGS_MENU, "🎯 Strategie & Criteria")

    labels = [item.label for item in strategy_menu.items if isinstance(item, SettingMenu)]
    assert "📝 Optie-strategie parameters" in labels

    actions = [item.action_id for item in strategy_menu.items if isinstance(item, SettingAction)]
    assert "run_rules_menu" in actions


def test_rules_menu_executes_actions(monkeypatch):
    actions = []
    monkeypatch.setattr(handlers, "run_module", lambda *a: actions.append(a))
    monkeypatch.setattr(handlers, "prompt", lambda *a, **k: "/tmp/crit.yaml")

    menu_holder = {}

    class FakeMenu:
        def __init__(self, title, exit_text="Terug"):
            menu_holder["title"] = title
            self.items = []
            menu_holder["items"] = self.items

        def add(self, desc, handler):
            self.items.append((desc, handler))

        def run(self):
            for _, handler in self.items:
                handler()

    monkeypatch.setattr(handlers, "Menu", FakeMenu)

    handlers.run_rules_menu(None, None)

    assert "Criteria beheren" in menu_holder["title"]
    descriptions = [desc for desc, _ in menu_holder["items"]]
    assert descriptions == [
        "Toon criteria",
        "Valideer criteria.yaml",
        "Valideer & reload",
        "Reload zonder validatie",
    ]
    assert actions == [
        ("tomic.cli.rules", "show"),
        ("tomic.cli.rules", "validate", "/tmp/crit.yaml"),
        ("tomic.cli.rules", "validate", "/tmp/crit.yaml", "--reload"),
        ("tomic.cli.rules", "reload"),
    ]

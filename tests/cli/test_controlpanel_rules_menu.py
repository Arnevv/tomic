import importlib
import types


def _extract(code_obj, name):
    for const in code_obj.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == name:
            return const
    return None


def _cell(value):
    return (lambda: value).__closure__[0]


def test_strategy_criteria_menu_contains_items(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    strat_code = _extract(mod.run_settings_menu.__code__, "run_strategy_criteria_menu")
    assert strat_code is not None

    calls = []
    def fake_option():
        calls.append("option")
    def fake_rules():
        calls.append("rules")

    func = types.FunctionType(
        strat_code,
        mod.run_settings_menu.__globals__,
        None,
        None,
        (
            _cell(fake_option),
            _cell(fake_rules),
        ),
    )

    menu_holder = {}
    class FakeMenu:
        def __init__(self, title, exit_text="Terug"):
            menu_holder["title"] = title
            self.items = []
            menu_holder["items"] = self.items
        def add(self, desc, handler):
            self.items.append((desc, handler))
        def run(self):
            pass
    monkeypatch.setattr(mod, "Menu", FakeMenu)

    func()

    assert "Strategie & Criteria" in menu_holder["title"]
    descriptions = [d for d, _ in menu_holder["items"]]
    assert "Optie-strategie parameters" in descriptions
    assert "Criteria beheren" in descriptions

    for _, handler in menu_holder["items"]:
        handler()
    assert calls == ["option", "rules"]


def test_rules_menu_executes_actions(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    rules_code = _extract(mod.run_settings_menu.__code__, "run_rules_menu")
    assert rules_code is not None

    func = types.FunctionType(
        rules_code,
        mod.run_settings_menu.__globals__,
        None,
        None,
        (),
    )

    actions = []
    monkeypatch.setattr(mod, "run_module", lambda *a: actions.append(a))
    monkeypatch.setattr(mod, "prompt", lambda *a, **k: "/tmp/crit.yaml")

    menu_holder = {}
    class FakeMenu:
        def __init__(self, title, exit_text="Terug"):
            menu_holder["title"] = title
            self.items = []
            menu_holder["items"] = self.items
        def add(self, desc, handler):
            self.items.append((desc, handler))
        def run(self):
            for _, h in self.items:
                h()
    monkeypatch.setattr(mod, "Menu", FakeMenu)

    func()

    assert "Criteria beheren" in menu_holder["title"]
    descriptions = [d for d, _ in menu_holder["items"]]
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

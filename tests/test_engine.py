"""Gate logic and parsing, with a stub in place of Jev (no network, no OS actions)."""

from voicecom import parse
from voicecom.engine import Engine
from voicecom.jev import Decision
from voicecom.platforms import Element


class StubAuto:
    def __init__(self):
        self.calls = []

    def frontmost_app(self): return "Google Chrome"
    def installed_apps(self): return ["Google Chrome", "Slack"]
    def clickable_elements(self): return [Element("Submit", "Button"), Element("Cancel", "Button")]
    def get_volume(self): return 40
    def say(self, text): pass

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, a))


class StubJev:
    def __init__(self, command, p, destructive=0.0, app=None, element=("Submit", 0.95), yes=0.95):
        self.d = Decision(command, p, p, destructive, app, 0.9 if app else 0.0, 0.1)
        self.element, self.yes = element, yes

    def decide(self, *a): return self.d
    def pick_element(self, transcript, elements, app):
        label, p = self.element
        return next((e for e in elements if e.label == label), None), p
    def is_yes(self, *a): return self.yes


def run(text, jev):
    auto = StubAuto()
    eng = Engine(auto, jev, speak=False)
    eng.handle(text)
    return auto, eng


def test_confident_runs():
    auto, eng = run("open chrome", StubJev("open_app", 0.97, app="Google Chrome"))
    assert auto.calls == [("open_app", ("Google Chrome",))] and eng.pending is None


def test_low_probability_is_ignored():
    auto, _ = run("hmm", StubJev("scroll_down", 0.3))
    assert auto.calls == []


def test_unsure_asks_then_runs_on_yes():
    auto, eng = run("make it bigger", StubJev("maximize_window", 0.6))
    assert auto.calls == [] and eng.pending
    eng.handle("yes")
    assert auto.calls == [("snap_window", ("max",))]


def test_destructive_asks_and_no_cancels():
    jev = StubJev("close_tab", 0.99, destructive=0.8, yes=0.05)
    auto, eng = run("close this tab", jev)
    assert eng.pending
    eng.handle("no wait")
    assert auto.calls == [] and eng.pending is None


def test_click_uses_second_choice():
    auto, _ = run("click submit", StubJev("click", 0.95, element=("Submit", 0.92)))
    assert auto.calls[0][0] == "click" and auto.calls[0][1][0].label == "Submit"


def test_click_unsure_element_asks():
    auto, eng = run("click the thing", StubJev("click", 0.95, element=("Cancel", 0.5)))
    assert auto.calls == [] and eng.pending


def test_parsers():
    assert parse.keys("Press Command-Shift-T.") == ["cmd", "shift", "t"]
    assert parse.number("set volume to twenty five percent") == 25
    assert parse.after("Search for pizza near me.", "search for") == "pizza near me"

"""Gate logic and parsing, with a stub in place of Jev (no network, no OS actions)."""

from dataclasses import replace

from voicecom import chain, parse
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
    def new_tab_target(self): return "Safari"
    def say(self, text): pass
    def search_url(self, q): return f"https://duckduckgo.com/?q={q}"

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, a))


class StubJev:
    """spans maps a Span's text to (command, p, destructive, app); unlisted Spans read as dictate."""

    def __init__(self, command, p, destructive=0.0, app=None, element=("Submit", 0.95), yes=0.95,
                 meaningful=0.99, app_p=None, spans=None):
        self.d = Decision(command, p, p, destructive, meaningful, app, app_p if app_p is not None else (0.9 if app else 0.0), 0.1)
        self.element, self.yes, self.spans = element, yes, spans or {}
        self.asked: list[str] = []

    def decide(self, transcript, front, apps, spans=()):
        self.asked = list(spans)
        out = []
        for text in spans:
            cmd, p, destr, app = self.spans.get(text, ("dictate", 0.9, 0.0, None))
            out.append(Decision(cmd, p, p, destr, self.d.meaningful, app, 1.0 if app else 0.0, 0.1))
        return replace(self.d, spans=out)
    def pick_element(self, transcript, elements, app):
        label, p = self.element
        return next((e for e in elements if e.label == label), None), p
    def is_yes(self, *a): return self.yes


def run(text, jev):
    auto = StubAuto()
    eng = Engine(auto, jev, speak=False, step_wait=0)
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


def test_parsing_survives_whisper_punctuation():  # issue #13
    assert parse.after("Type. Hello guys.", "type", keep_end=True) == "Hello guys."
    assert parse.after("type see you tomorrow", "type", keep_end=True) == "see you tomorrow"
    assert parse.after("Web Search. Banana.", "web search", "search") == "Banana"
    assert parse.after("Web search banana", "web search", "search") == "banana"
    assert parse.after("Open. Safari.", "open") == "Safari"
    assert parse.keys("Press. Enter.") == ["enter"]


def test_new_tab_names_its_target_app():  # issue #14
    auto, _ = run("new tab", StubJev("new_tab", 0.99))
    assert auto.calls == [("new_tab", ("Safari",))]


def test_filler_is_ignored():  # issue #11
    auto, eng = run("uh hmm", StubJev("dictate", 1.0, meaningful=0.05))
    assert auto.calls == [] and eng.pending is None


def test_unsure_app_pick_confirms_instead_of_literal_name():  # issue #12
    auto, eng = run("open my email", StubJev("open_app", 0.98, app="Mail", app_p=0.2))
    assert auto.calls == [] and eng.pending and "Mail" in eng.pending[1]


def test_spoken_installed_name_wins_over_weak_pick():  # issue #12
    auto, _ = run("open slack", StubJev("open_app", 0.98, app="Google Chrome", app_p=0.4))
    assert auto.calls == [("open_app", ("Slack",))]


# ---------------------------------------------------------------- Chains (issue #18)
def test_pieces_split_on_spoken_boundaries():
    def texts(t): return [t[a:b] for a, b in chain.pieces(t)]
    assert texts("open Safari and search for tacos") == ["open Safari", "search for tacos"]
    assert texts("Open Safari. Then search for tacos.") == ["Open Safari", "search for tacos."]
    assert texts("snap this left, open Notes and then snap it right") == ["snap this left", "open Notes", "snap it right"]
    assert chain.spans("scroll down") == []


SAFARI_TACOS = {"open Safari": ("open_app", 1.0, 0.0, "Safari"),
                "search for tacos": ("web_search", 0.99, 0.0, None)}


def test_two_commands_in_one_sentence_run_in_order():
    jev = StubJev("web_search", 0.55, spans=SAFARI_TACOS)
    auto, _ = run("open Safari and search for tacos", jev)
    assert [c[0] for c in auto.calls] == ["open_app", "open_url"]
    assert auto.calls[0][1] == ("Safari",) and "tacos" in auto.calls[1][1][0]
    assert jev.asked == ["open Safari", "search for tacos"]  # same single request as the whole sentence


def test_and_inside_one_command_is_not_split():
    jev = StubJev("type_text", 0.98, spans={"type salt": ("type_text", 0.95, 0.0, None)})
    auto, _ = run("type salt and pepper", jev)
    assert auto.calls == [("type_text", ("salt and pepper",))]


def test_split_keeps_a_multi_word_tail_together():
    jev = StubJev("web_search", 0.5, spans={**SAFARI_TACOS, "search for tacos and pizza": ("web_search", 0.97, 0.0, None)})
    auto, _ = run("open Safari and search for tacos and pizza", jev)
    assert [c[0] for c in auto.calls] == ["open_app", "open_url"] and "pizza" in auto.calls[1][1][0]


def test_destructive_step_confirms_the_whole_chain_once():
    jev = StubJev("close_tab", 0.6, spans={"open Safari": ("open_app", 1.0, 0.0, "Safari"),
                                           "close this tab": ("close_tab", 0.99, 0.9, None)})
    auto, eng = run("open Safari then close this tab", jev)
    assert auto.calls == [] and "open Safari, then close tab" in eng.pending[1]
    eng.handle("yes")
    assert [c[0] for c in auto.calls] == ["open_app", "close_tab"]


def test_unparseable_step_runs_nothing():
    jev = StubJev("set_volume", 0.5, spans={"set the volume": ("set_volume", 0.95, 0.0, None),
                                            "open Safari": ("open_app", 1.0, 0.0, "Safari")})
    auto, eng = run("set the volume and open Safari", jev)
    assert auto.calls == [] and eng.pending is None


def test_chain_is_capped_at_five_steps():
    words = ["scroll down", "scroll up", "mute", "new tab", "scroll down a bit", "scroll up a bit"]
    jev = StubJev("dictate", 0.5, spans={w: ("scroll_down", 0.95, 0.0, None) for w in words})
    auto, _ = run(", ".join(words), jev)
    assert len(auto.calls) <= 1  # six confident pieces can't become six steps


def test_click_after_other_steps_reads_the_screen_at_its_turn():
    jev = StubJev("dictate", 0.5, spans={"open Safari": ("open_app", 1.0, 0.0, "Safari"),
                                         "click Submit": ("click", 0.97, 0.0, None)})
    auto, _ = run("open Safari then click Submit", jev)
    assert [c[0] for c in auto.calls] == ["open_app", "click"]


def test_type_drops_whispers_period_but_keeps_questions():
    auto, _ = run("Type hello.", StubJev("type_text", 0.99))
    assert auto.calls == [("type_text", ("hello",))]
    auto, _ = run("Type are you free?", StubJev("type_text", 0.99))
    assert auto.calls == [("type_text", ("are you free?",))]

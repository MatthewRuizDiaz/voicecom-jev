"""Transcript -> Jev decision -> confidence gate -> deterministic action, with a one-line log."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import commands  # noqa: F401  (registers the commands)
from .jev import Jev
from .registry import REGISTRY, Ctx, Plan


@dataclass
class Thresholds:
    act: float = 0.80        # command probability needed to run without asking
    ignore: float = 0.40     # below this, do nothing
    destructive: float = 0.50  # Noul above this always asks first
    element_act: float = 0.70
    element_ignore: float = 0.30
    yes: float = 0.70        # confirmation Noul


GREEN, YELLOW, GREY, RED, BOLD, RESET = "\033[32m", "\033[33m", "\033[90m", "\033[31m", "\033[1m", "\033[0m"
CLICKY = re.compile(r"\b(click|tap|press|select|hit|choose|push)\b", re.I)


class Engine:
    def __init__(self, auto, jev: Jev, thresholds: Thresholds | None = None, speak: bool = True,
                 dry_run: bool = False):
        self.auto, self.jev, self.t = auto, jev, thresholds or Thresholds()
        self.dry_run = dry_run
        self.speak = speak
        self.pending: tuple[Plan, str, float] | None = None  # plan, question, asked-at
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.apps = auto.installed_apps()

    def handle(self, transcript: str, stt_s: float = 0.0) -> None:
        start = time.perf_counter()
        transcript = transcript.strip()
        if not transcript:
            return
        if self.pending and time.time() - self.pending[2] < 30:
            return self._answer_confirmation(transcript)
        self.pending = None

        front = self.auto.frontmost_app()
        # Read the accessibility tree while Jev decides, if this sounds like a click.
        elements_f = self.pool.submit(self.auto.clickable_elements) if CLICKY.search(transcript) else None
        d = self.jev.decide(transcript, front, self.apps)

        cmd = REGISTRY[d.command]
        ctx = Ctx(transcript, self.auto, self.jev, app=d.app, app_p=d.app_p)
        if d.command == "click" and elements_f is not None:
            ctx.elements = elements_f.result()

        head = (f'"{transcript}" -> {BOLD}{d.command}{RESET} p={d.p:.2f} conf={d.confidence:.2f} '
                f"destr={d.destructive:.2f}")
        if cmd.uses_app and d.app:
            head += f" app={d.app}({d.app_p:.2f})"

        if d.p < self.t.ignore:
            return self._log(head, f"{GREY}IGNORED (unsure){RESET}", stt_s, d.latency, start)

        plan = cmd.plan(ctx)
        if plan is None:
            return self._log(head, f"{GREY}IGNORED (couldn't parse arguments){RESET}", stt_s, d.latency, start)
        if plan.p is not None:
            head += f" target_p={plan.p:.2f}"
            if plan.p < self.t.element_ignore:
                return self._log(head, f"{GREY}IGNORED ({plan.summary}){RESET}", stt_s, d.latency, start)

        unsure = d.p < self.t.act or (plan.p is not None and plan.p < self.t.element_act)
        risky = d.destructive >= self.t.destructive
        if unsure or risky:
            why = "destructive" if risky else "unsure"
            question = f"Confirm: {plan.summary}?"
            self.pending = (plan, question, time.time())
            self._log(head, f"{YELLOW}CONFIRM ({why}): {plan.summary} - say yes or no{RESET}",
                      stt_s, d.latency, start)
            if self.speak:
                self.auto.say(question)
            return

        self._run(plan, head, stt_s, d.latency, start)

    def _answer_confirmation(self, reply: str) -> None:
        plan, question, _ = self.pending
        self.pending = None
        t = time.perf_counter()
        yes = self.jev.is_yes(reply, question)
        head = f'"{reply}" -> confirm yes={yes:.2f}'
        if yes >= self.t.yes:
            self._run(plan, head, 0.0, time.perf_counter() - t, t)
        else:
            self._log(head, f"{GREY}CANCELLED: {plan.summary}{RESET}", 0.0, time.perf_counter() - t, t)

    def _run(self, plan: Plan, head: str, stt_s: float, jev_s: float, start: float) -> None:
        try:
            plan.do()
            result = f"{GREEN}{'WOULD RUN' if self.dry_run else 'RAN'}: {plan.summary}{RESET}"
        except Exception as e:  # a demo tool: report and keep listening
            result = f"{RED}FAILED: {plan.summary} ({e}){RESET}"
        self._log(head, result, stt_s, jev_s, start)

    def _log(self, head: str, result: str, stt_s: float, jev_s: float, start: float) -> None:
        total = stt_s + (time.perf_counter() - start)
        print(f"{time.strftime('%H:%M:%S')} {head} | stt={stt_s:.2f}s jev={jev_s:.2f}s "
              f"total={total:.2f}s | {result}", flush=True)

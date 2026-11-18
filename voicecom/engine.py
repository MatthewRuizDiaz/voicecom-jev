"""Transcript -> Jev decision -> confidence gate -> deterministic action, with a one-line log."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import chain, commands  # noqa: F401  (commands registers the commands)
from .jev import Jev
from .registry import REGISTRY, Ctx, Plan


@dataclass
class Thresholds:
    act: float = 0.80        # command probability needed to run without asking
    ignore: float = 0.40     # below this, do nothing
    destructive: float = 0.50  # Noul above this always asks first
    meaningful: float = 0.30   # Noul below this is filler ("uh", "hmm") and is ignored
    element_act: float = 0.70   # click element probability to run
    element_ignore: float = 0.30
    yes: float = 0.70        # confirmation Noul


GREEN, YELLOW, GREY, RED, BOLD, RESET = "\033[32m", "\033[33m", "\033[90m", "\033[31m", "\033[1m", "\033[0m"
CLICKY = re.compile(r"\b(click|tap|press|select|hit|choose|push)\b", re.I)


class Engine:
    def __init__(self, auto, jev: Jev, thresholds: Thresholds | None = None, speak: bool = True,
                 dry_run: bool = False, step_wait: float | None = None):
        self.auto, self.jev, self.t = auto, jev, thresholds or Thresholds()
        self.dry_run = dry_run
        # Longest wait for one Chain step to take effect (e.g. the opened app coming to the front).
        self.step_wait = (0.0 if dry_run else 2.0) if step_wait is None else step_wait
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
        found = chain.spans(transcript)
        # Read the accessibility tree while Jev decides, if this sounds like a click.
        elements_f = self.pool.submit(self.auto.clickable_elements) if CLICKY.search(transcript) else None
        d = self.jev.decide(transcript, front, self.apps, [s.text for s in found])
        takes_rest = REGISTRY[d.command].takes_rest and d.p >= self.t.act  # e.g. "open Notes and type hi" is one note
        if d.meaningful >= self.t.meaningful and not takes_rest:
            steps = chain.best_split(found, d.spans, self.t.act,
                                     takes_rest=frozenset(c.name for c in REGISTRY.values() if c.takes_rest))
            if steps:
                return self._handle_chain(transcript, steps, d, elements_f, stt_s, start)

        cmd = REGISTRY[d.command]
        ctx = Ctx(transcript, self.auto, self.jev, app=d.app, app_p=d.app_p, apps=self.apps)
        if d.command == "click" and elements_f is not None:
            ctx.elements = elements_f.result()

        head = (f'"{transcript}" -> {BOLD}{d.command}{RESET} p={d.p:.2f} conf={d.confidence:.2f} '
                f"destr={d.destructive:.2f}")
        if cmd.uses_app and d.app:
            head += f" app={d.app}({d.app_p:.2f})"

        if d.meaningful < self.t.meaningful:
            head += f" meaningful={d.meaningful:.2f}"
            return self._log(head, f"{GREY}IGNORED (filler){RESET}", stt_s, d.latency, start)
        if d.p < self.t.ignore:
            return self._log(head, f"{GREY}IGNORED (unsure){RESET}", stt_s, d.latency, start)

        plan = cmd.plan(ctx)
        if plan is None:
            return self._log(head, f"{GREY}IGNORED (couldn't parse arguments){RESET}", stt_s, d.latency, start)
        if plan.p is not None:
            head += f" target_p={plan.p:.2f}"
            if plan.p < self.t.element_ignore:
                return self._log(head, f"{GREY}IGNORED ({plan.summary}){RESET}", stt_s, d.latency, start)

        unsure = (d.p < self.t.act or (plan.p is not None and plan.p < self.t.element_act)
                  or plan.confirm)
        risky = d.destructive >= self.t.destructive
        if unsure or risky:
            return self._ask(plan, head, "destructive" if risky else "unsure", stt_s, d.latency, start)

        self._run(plan, head, stt_s, d.latency, start)

    def _handle_chain(self, transcript, steps, d, elements_f, stt_s, start) -> None:
        """Plan every Step first, then one decision for the whole Chain: run, confirm, or ignore."""
        head = (f'"{transcript}" -> chain ' + " → ".join(f"{BOLD}{sd.command}{RESET}({sd.p:.2f})" for _, sd in steps)
                + f" destr={max(sd.destructive for _, sd in steps):.2f}")
        planned: list[tuple] = []  # (span text, step decision, plan or None = plan a click at its turn)
        unsure = False
        for i, (span, sd) in enumerate(steps):
            ctx = Ctx(span.text, self.auto, self.jev, app=sd.app, app_p=sd.app_p, apps=self.apps)
            if sd.command == "click" and i > 0:
                planned.append((span.text, sd, None))  # the screen changes after the earlier steps
                continue
            if sd.command == "click" and elements_f is not None:
                ctx.elements = elements_f.result()
            plan = REGISTRY[sd.command].plan(ctx)
            if plan is None or (plan.p is not None and plan.p < self.t.element_ignore):
                why = plan.summary if plan else "couldn't parse"
                return self._log(head, f'{GREY}IGNORED (step {i + 1} "{span.text}": {why}){RESET}',
                                 stt_s, d.latency, start)
            unsure |= plan.confirm or (plan.p is not None and plan.p < self.t.element_act)
            planned.append((span.text, sd, plan))

        summary = ", then ".join(p.summary if p else f"click ({text})" for text, _, p in planned)
        plan = Plan(summary, lambda: self._run_steps(planned))
        risky = any(sd.destructive >= self.t.destructive for _, sd, _ in planned)
        if unsure or risky:
            return self._ask(plan, head, "destructive" if risky else "unsure", stt_s, d.latency, start)
        self._run(plan, head, stt_s, d.latency, start)

    def _run_steps(self, planned) -> None:
        for i, (text, sd, plan) in enumerate(planned):
            if i:
                self._settle(planned[i - 1][2])
            if plan is None:  # a click after earlier steps: read the screen now
                ctx = Ctx(text, self.auto, self.jev, apps=self.apps)
                plan = REGISTRY["click"].plan(ctx)
                if plan.p is None or plan.p < self.t.element_act:
                    raise RuntimeError(f"stopped at step {i + 1}: {plan.summary} (p={plan.p or 0:.2f})")
            plan.do()

    def _settle(self, prev: Plan | None) -> None:
        """Wait for the previous Step to take effect before the next one acts on the screen."""
        if self.step_wait <= 0:
            return
        app = prev.extra.get("front") if prev else None
        if app:
            deadline = time.time() + self.step_wait
            while self.auto.frontmost_app() != app and time.time() < deadline:
                time.sleep(0.02)
        time.sleep(prev.extra.get("settle", 0.25) if prev else 0.25)

    def _ask(self, plan: Plan, head: str, why: str, stt_s: float, jev_s: float, start: float) -> None:
        question = f"Confirm: {plan.summary}?"
        self.pending = (plan, question, time.time())
        self._log(head, f"{YELLOW}CONFIRM ({why}): {plan.summary} - say yes or no{RESET}", stt_s, jev_s, start)
        if self.speak:
            self.auto.say(question)

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

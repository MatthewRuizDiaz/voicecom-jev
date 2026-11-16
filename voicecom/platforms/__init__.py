import platform

from .base import Automation, DryRun, Element


def get_automation(warn: bool = True) -> Automation:
    system = platform.system()
    if system == "Darwin":
        from .macos import MacAutomation

        return MacAutomation(warn)
    raise SystemExit(
        f"voicecom-jev only has a macOS automation layer so far (detected {system}). "
        "Add one by implementing voicecom/platforms/base.py:Automation."
    )


__all__ = ["Automation", "DryRun", "Element", "get_automation"]

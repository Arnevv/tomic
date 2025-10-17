from __future__ import annotations

from typing import Callable, List, Optional


def prompt(text: str, default: Optional[str] = None) -> str:
    """Prompt the user for input and return the stripped value.

    Surrounding single or double quotes entered by the user are stripped to
    avoid issues when paths are copied with quotes.
    """
    val = input(text).strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1]
    return val if val else (default or "")


def prompt_float(text: str, default: Optional[float] = None) -> Optional[float]:
    """Prompt for a floating point value with optional default."""
    while True:
        val = input(text).strip().replace(",", ".")
        if val == "" and default is not None:
            return default
        if val == "" and default is None:
            return None
        try:
            return float(val)
        except ValueError:
            print("❌ Ongeldige invoer, probeer opnieuw.")


def prompt_yes_no(text: str, default: bool = False) -> bool:
    """Prompt for a yes/no question and return ``True`` for yes."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    val = prompt(text + suffix)
    if not val:
        return default
    return val.lower().startswith(("y", "j"))


class Menu:
    """Simple interactive menu helper."""

    def __init__(self, title: str, exit_text: str = "Terug") -> None:
        self.title = title
        self.exit_text = exit_text
        self.items: List[tuple[str, Callable[[], None]]] = []

    def add(self, description: str, handler: Callable[[], None]) -> None:
        self.items.append((description, handler))

    def run(self) -> None:
        while True:
            print(f"\n=== {self.title} ===")
            for idx, (desc, _) in enumerate(self.items, start=1):
                print(f"{idx}. {desc}")
            print(f"{len(self.items)+1}. {self.exit_text}")
            try:
                choice = input("Maak je keuze: ").strip()
            except (EOFError, StopIteration):  # pragma: no cover - interactive safeguard
                return
            if choice == str(len(self.items)+1):
                break
            try:
                index = int(choice) - 1
                handler = self.items[index][1]
            except (ValueError, IndexError):
                print("❌ Ongeldige keuze")
                continue
            handler()

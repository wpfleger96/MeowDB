from __future__ import annotations

from rich.console import Console

ICON_ERROR = "[bold red]✗[/bold red]"
ICON_SUCCESS = "[bold green]✓[/bold green]"
ICON_WARNING = "[bold yellow]![/bold yellow]"
ICON_HINT = "[bold blue]→[/bold blue]"
ICON_INFO = "[dim]·[/dim]"


console = Console()


def print_error(message: str) -> None:
    console.print(f"{ICON_ERROR} {message}")


def print_success(message: str) -> None:
    console.print(f"{ICON_SUCCESS} {message}")


def print_warning(message: str) -> None:
    console.print(f"{ICON_WARNING} {message}")


def print_hint(message: str) -> None:
    console.print(f"{ICON_HINT} {message}")


def print_info(message: str) -> None:
    console.print(f"{ICON_INFO} {message}")

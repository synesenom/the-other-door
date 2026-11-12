"""`serve`: door for a phone (#302). The MCP tools over HTTP for this data folder, and its paired phones.

`serve` (`serve start`) runs `door.serve_http`'s app on this machine (127.0.0.1:8765 unless told
otherwise); a tunnel (Cloudflare, Tailscale) gives it the HTTPS address a phone installs the app from.
`serve pair` makes a one-time code for a phone, `serve devices` lists the paired ones and
`serve unpair` revokes one. One data folder per person: each runs its own `serve` on its own port.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import click

from door.core import instances, launch_agent, pairing, workspace

DEFAULT_PORT = 8765


def _default_web_dir() -> Path:
    return workspace.REPO_ROOT / "app" / "out" / "web"


def _profile_config(home: Path) -> dict:
    try:
        data = json.loads((home / "profile" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _profile_name(home: Path) -> str | None:
    """The first name in the profile, for the installed app's name ("The other door — Anna")."""
    try:
        name = json.loads((home / "profile" / "config.json").read_text(encoding="utf-8")).get("name") or ""
    except (OSError, ValueError):
        return None
    return name.split()[0] if name.strip() else None


def _serve_core(*, home: Path, host: str, port: int, name: str | None, web_dir: Path) -> dict:
    """Where the server will listen and what it serves; never starts it."""
    home = Path(home)
    return {
        "home": str(home.resolve()),
        "url": f"http://{host}:{port}",
        "host": host,
        "port": port,
        "name": name or _profile_name(home) or "",
        "web_dir": str(web_dir),
        "web_built": (Path(web_dir) / "index.html").is_file(),
        "devices": len(pairing.devices(home)),
    }


def _pair_core(*, home: Path, device: str, url: str | None) -> dict:
    code = pairing.new_code(home, device)
    link = f"{url.rstrip('/')}/#pair={code}" if url else None
    return {"device": device.strip(), "code": code, "expires_in_minutes": int(pairing.CODE_TTL.total_seconds() // 60), "link": link}


def _run_server(app, host: str, port: int) -> None:  # pragma: no cover - the real server; tests replace it
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning", server_header=False, date_header=False)


@click.group("serve", invoke_without_command=True)
@click.pass_context
def serve_group(ctx: click.Context):
    """The other door for your phone: the app and its tools over HTTP, for paired phones.

    `serve` starts it; `pair`, `devices` and `unpair` manage the phones that may use it."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(start)


@click.command("start")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Where to listen. Only this machine by default; a tunnel brings the phone here.")
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int, help="The port; one per person.")
@click.option("--name", default=None, help="The name the installed app shows (\"The other door — Anna\"); default: the profile's first name.")
@click.option("--web", "web_dir", default=None, type=click.Path(path_type=Path),
              help="The phone app's build (default: app/out/web, made by `npm run build:web`).")
def start(host: str, port: int, name: str | None, web_dir: Path | None):
    """Start the server for this data folder (Ctrl-C stops it)."""
    from door import mcp_server, serve_http

    info = _serve_core(home=workspace.HOME, host=host, port=port, name=name, web_dir=web_dir or _default_web_dir())
    click.echo(f"The other door is serving {info['home']} at {info['url']}")
    if not info["web_built"]:
        click.echo("The phone app is not built yet: `cd app && npm run build:web`, then start again.")
    click.echo(f"Paired phones: {info['devices']}. Pair one with `./door serve pair --device \"<name>\"`.")
    try:  # one instance per person: its own port and its own Claude plan
        instances.register(workspace.HOME, port=port, name=info["name"],
                           claude_config_dir=_profile_config(Path(workspace.HOME)).get("claude_config_dir"))
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    mcp_server._startup_pull()
    app = serve_http.build_app(home=workspace.HOME, web_dir=Path(info["web_dir"]), name=info["name"])
    _run_server(app, host, port)


@click.command("pair")
@click.option("--device", required=True, help="A name for the phone, e.g. \"Anna's Pixel\".")
@click.option("--url", default=None, help="The address the phone opens (your tunnel's https://…): adds a link and a QR code.")
def pair(device: str, url: str | None):
    """Make a one-time code that pairs a phone (valid 10 minutes)."""
    try:
        result = _pair_core(home=workspace.HOME, device=device, url=url)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Pairing code for {result['device']}: {result['code']}")
    click.echo(f"It works once, for {result['expires_in_minutes']} minutes. Type it in the app on the phone.")
    if result["link"]:
        import segno

        click.echo(f"Or open this on the phone: {result['link']}")
        out = io.StringIO()
        segno.make(result["link"]).terminal(out=out, compact=True)
        click.echo(out.getvalue())


@click.command("devices")
def devices():
    """The phones paired with this data folder."""
    rows = pairing.devices(workspace.HOME)
    if not rows:
        click.echo("No phone is paired. `./door serve pair --device \"<name>\"` makes a code for one.")
        return
    for d in rows:
        seen = d.get("last_seen") or "never"
        click.echo(f"{d['device']}  paired {str(d.get('paired_at'))[:10]}  last seen {str(seen)[:16].replace('T', ' ')}")


@click.command("unpair")
@click.argument("device")
def unpair(device: str):
    """Revoke a phone: it can no longer reach The other door until paired again."""
    if not pairing.unpair(workspace.HOME, device):
        click.echo(f"Error: no paired phone is called {device!r} (`./door serve devices` lists them).", err=True)
        sys.exit(1)
    click.echo(f"Unpaired {device}.")


@click.command("install-agent")
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int, help="The port; one per person.")
@click.option("--name", default=None, help="Whose instance (the app's name too); default: the profile's first name.")
def install_agent(port: int, name: str | None):
    """macOS: start this data folder's server at login and keep it running."""
    name = name or _profile_name(Path(workspace.HOME)) or "door"
    try:
        path = launch_agent.install(home=workspace.HOME, port=port, name=name)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"The other door for {name} now starts at login and restarts if it stops ({path}).")
    click.echo(f"Its log: {Path(workspace.HOME) / 'logs' / 'serve.log'}")


@click.command("uninstall-agent")
@click.option("--name", default=None, help="Whose instance; default: the profile's first name.")
def uninstall_agent(name: str | None):
    """macOS: stop starting this data folder's server at login."""
    name = name or _profile_name(Path(workspace.HOME)) or "door"
    try:
        path = launch_agent.uninstall(name=name)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Removed {path}." if path else f"No launch agent for {name}.")

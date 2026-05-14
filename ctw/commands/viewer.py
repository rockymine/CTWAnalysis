"""'viewer' subcommand — start the CTW map browser visualization server."""

import argparse
import webbrowser


def register(subparsers) -> None:
    p = subparsers.add_parser(
        'viewer',
        help='Start the browser-based map visualization server',
    )
    p.add_argument('--port', type=int, default=7891,
                   help='Port to listen on (default: 7891)')
    p.add_argument('--no-browser', action='store_true',
                   help='Do not open the browser automatically')
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> None:
    from map_viewer.app import create_app
    import logging
    log = logging.getLogger('ctw')

    app = create_app()
    url = f"http://localhost:{args.port}"
    log.info("Map viewer running at %s", url)

    if not args.no_browser:
        webbrowser.open(url)

    app.run(host="127.0.0.1", port=args.port, debug=False)

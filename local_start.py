"""Start the Windows desktop launcher on loopback, not the public network."""
import socket
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 5000


def open_when_ready(process_timeout=30):
    """Open the browser only after the server starts accepting connections."""
    deadline = time.monotonic() + process_timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                webbrowser.open(f"http://{HOST}:{PORT}")
                return
        except OSError:
            time.sleep(0.25)
    print(f"Could not open the browser automatically. Visit http://{HOST}:{PORT}", flush=True)


def main():
    # Avoid opening some other program's page when the port is already in use.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError:
            print(f"Port {PORT} is already in use. Close the other program and try again.", flush=True)
            return 1

    import app

    app.start_scheduler()
    threading.Thread(target=open_when_ready, daemon=True).start()
    app.app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

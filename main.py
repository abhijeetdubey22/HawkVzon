"""
HawkVzon AI — HostelOS & Edge Security Command Center
Universal Application Entrypoint (main.py)

Track: Enterprise AI & Smart Cities
Google DeepMind | Google Cloud — Startup Buildathon India 2026
Team: HawkVzon AI (Abhijeet Dubey & Keval Shinde)

Usage:
    python main.py              # Starts the Web Surveillance & Telemetry Portal (Port 5000)
    python main.py --gui        # Starts the Tkinter Desktop Command Center
    python main.py --test       # Runs the Automated Test Suite
    python main.py --port 8080  # Starts Web Portal on custom port
"""
import sys
import os

# Ensure current directory is on PYTHONPATH
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def print_banner():
    print("=" * 72)
    print("   🦅  HAWKVZON AI — HOSTELOS & EDGE SECURITY COMMAND CENTER")
    print("   Google DeepMind | Google Cloud — Startup Buildathon India 2026")
    print("   Track: Enterprise AI & Smart Cities")
    print("   Team: HawkVzon AI (Abhijeet Dubey & Keval Shinde)")
    print("=" * 72)

def run():
    print_banner()
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("\nAvailable Options:")
        print("  python main.py          -> Launch Web Surveillance Portal on http://localhost:5000")
        print("  python main.py --gui    -> Launch Desktop Command Center (Tkinter GUI)")
        print("  python main.py --test   -> Run Automated Verification Test Suite")
        print("  python main.py --port N -> Run Web Portal on custom port N (e.g. --port 8080)")
        return

    if "--test" in args:
        print("\n[RUNNING TEST SUITE]")
        import unittest
        import test_suite
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_suite.TestFaceEmotionSystem)
        runner = unittest.TextTestRunner(verbosity=1)
        res = runner.run(suite)
        sys.exit(0 if res.wasSuccessful() else 1)

    if "--gui" in args:
        print("\n[LAUNCHING DESKTOP COMMAND CENTER]")
        import tkinter as tk
        from gui_app import App
        root = tk.Tk()
        app = App(root)
        root.mainloop()
        return

    # Default action: Launch Web Portal (web_server.py)
    port = 5000
    for i, a in enumerate(args):
        if a in ("--port", "-p") and i + 1 < len(args) and args[i + 1].isdigit():
            port = int(args[i + 1])
        elif a.isdigit():
            port = int(a)

    print(f"\n[LAUNCHING WEB SURVEILLANCE COMMAND CENTER ON PORT {port}]")
    from web_server import run_server
    run_server(port=port)

if __name__ == "__main__":
    run()

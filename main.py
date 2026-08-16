from pathlib import Path
import subprocess
from datetime import datetime

def main():
    # first: add a function to do checks that niri is present/ ipc is callable
    # also verify that the env var for the server has a reachable URL

    out = Path.home() / "Pictures" / "Screenshots"
    out.mkdir(parents=True, exist_ok=True)

    filename = out / f"screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    filename = filename.resolve()

    subprocess.run([
        "niri", "msg", "action", "screenshot",
        "--path", str(filename),
    ], check=True)

    print(filename)

if __name__ == "__main__":
    main()

# want to time how long it takes for the OCR to happen 
# also print the output 
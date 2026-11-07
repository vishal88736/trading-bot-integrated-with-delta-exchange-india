import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from bot.web import create_app


def main():
    parser = argparse.ArgumentParser(description="Delta India demo trading dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--runtime", type=Path, default=Path(".runtime"))
    args = parser.parse_args()
    load_dotenv()
    # Loopback only. Credentials and trading controls belong on the local machine.
    uvicorn.run(create_app(args.runtime), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()

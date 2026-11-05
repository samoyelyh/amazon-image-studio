import argparse
from pathlib import Path

from .core import BridgeSettings, initialize_config


def main():
    parser = argparse.ArgumentParser(description="Native Codex image executor (no OpenAI API key)")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--init-config", action="store_true")
    args = parser.parse_args()
    if args.init_config:
        initialize_config(args.config)
        print("Local bridge configuration created. Token is not displayed.")
        return
    settings = BridgeSettings.model_validate_json(args.config.read_text(encoding="utf-8"))
    from .api import create_bridge_app
    import uvicorn
    uvicorn.run(create_bridge_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()

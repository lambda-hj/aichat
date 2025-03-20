import os
import sys
from aiohttp import web
from aichat.server import create_app


def main():
    """
    Run the WebRTC server for audio/video recording
    """
    app = create_app()
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8080))
    
    print(f"Starting WebRTC server on http://0.0.0.0:{port}")
    print(f"Audio recordings will be saved to: {os.path.abspath('aichat/recordings/audio')}")
    print(f"Video recordings will be saved to: {os.path.abspath('aichat/recordings/video')}")
    
    # Run the web server
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

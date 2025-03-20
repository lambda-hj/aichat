import asyncio
import datetime
import os
import platform  # Add platform detection
import uuid
import wave
from pathlib import Path
from typing import Dict, Optional

import av
import cv2
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder, MediaRelay

# Paths for storing recordings
AUDIO_ROOT = Path(__file__).parent / "recordings" / "audio"
VIDEO_ROOT = Path(__file__).parent / "recordings" / "video"
RECORDING_ROOT = Path(__file__).parent / "recordings"

# Ensure directories exist
AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
RECORDING_ROOT.mkdir(parents=True, exist_ok=True)

# Store active peer connections
pcs = set()
relay = MediaRelay()

# Store active recorders
recorders = {}

# Global webcam players
webcam = None

def create_local_tracks(play_from=None):
    """
    Create media tracks for WebRTC.
    
    Args:
        play_from: Optional file path to play media from instead of live camera/mic
        
    Returns:
        Tuple of (audio_track, video_track)
    """
    global relay, webcam
    
    # If playing from a file
    if play_from:
        player = MediaPlayer(play_from)
        return player.audio, player.video
    
    # For live media
    options = {"framerate": "30", "video_size": "640x480"}
    audio_options = {"channels": "1", "sample_rate": "48000"}
    
    if webcam is None:
        try:
            # Try platform-specific camera sources
            if platform.system() == "Darwin":  # macOS
                webcam = MediaPlayer(
                    "default:default", format="avfoundation", options={**options, **audio_options}
                )
            elif platform.system() == "Windows":
                webcam = MediaPlayer(
                    "audio=Microphone (Realtek Audio):video=Integrated Camera", 
                    format="dshow", 
                    options={**options, **audio_options}
                )
            else:  # Linux
                webcam = MediaPlayer(
                    "default:v4l2:/dev/video0", 
                    format="v4l2", 
                    options={**options, **audio_options}
                )
                
            # Check if tracks are available
            if webcam.audio is None and webcam.video is None:
                raise ValueError("No audio or video tracks available from devices")
                
        except Exception as e:
            print(f"Could not access camera/microphone: {e}, using test sources instead")
            # Fall back to test sources
            audio_src = MediaPlayer(
                "anullsrc=r=48000:cl=mono", 
                format="lavfi", 
                options={"sample_rate": "48000", "channels": "1"}
            )
            video_src = MediaPlayer(
                "testsrc=size=640x480:rate=30", 
                format="lavfi"
            )
            return audio_src.audio, video_src.video
    
    # If we have a webcam but one of the tracks is missing, create synthetic ones
    audio_track = webcam.audio
    video_track = webcam.video
    
    if audio_track is None:
        print("Creating synthetic audio source as fallback")
        audio_src = MediaPlayer(
            "anullsrc=r=48000:cl=mono", 
            format="lavfi", 
            options={"sample_rate": "48000", "channels": "1"}
        )
        audio_track = audio_src.audio
        
    if video_track is None:
        print("Creating synthetic video source as fallback")
        video_src = MediaPlayer(
            "testsrc=size=640x480:rate=30", 
            format="lavfi"
        )
        video_track = video_src.video

    # Return both tracks with relay to allow multiple consumers
    return relay.subscribe(audio_track), relay.subscribe(video_track)


async def index(request):
    """Serve the index.html page"""
    content = open(os.path.join(os.path.dirname(__file__), "static/index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    """Serve the client.js file"""
    content = open(os.path.join(os.path.dirname(__file__), "static/client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def offer(request):
    """Handle WebRTC offer from client"""
    try:
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        
        # Generate a unique ID for this user session
        user_id = str(uuid.uuid4())
        print(f"New WebRTC connection from user: {user_id}")
        
        # Create a new peer connection
        pc = RTCPeerConnection()
        pcs.add(pc)
        
        # Create a recorder for this session
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        recorder_path = str(RECORDING_ROOT / f"{user_id}_{timestamp}.mp4")
        print(f"Creating recorder at path: {recorder_path}")
        
        # Create recorder with proper options for audio/video
        recorder = MediaRecorder(
            recorder_path,
            format="mp4"  # Use mp4 container format
        )
        recorders[user_id] = recorder
        
        # Create local media tracks
        try:
            local_audio, local_video = create_local_tracks()
        except Exception as e:
            print(f"Error creating local tracks: {e}")
            local_audio, local_video = None, None
        
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"Connection state is {pc.connectionState}")
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                await pc.close()
                pcs.discard(pc)
                
                # Stop recording
                if user_id in recorders:
                    rec = recorders.pop(user_id)
                    if hasattr(rec, '_started') and rec._started:
                        print(f"Stopping recording: {recorder_path}")
                        await rec.stop()
                        print(f"Recording stopped: {recorder_path}")
                    
        @pc.on("track")
        def on_track(track):
            print(f"Track {track.kind} received from peer: {track.kind}")
            
            # Add the track to the recorder
            recorder.addTrack(track)
            
            # Start the recorder when we get the first track
            if not hasattr(recorder, '_started') or not recorder._started:
                print(f"Starting recording to {recorder_path}")
                asyncio.ensure_future(recorder.start())
            
            # Send back appropriate track to peer (for preview)
            if track.kind == "audio":
                # Use local audio if available, otherwise echo back
                if local_audio:
                    pc.addTrack(local_audio)
                else:
                    pc.addTrack(relay.subscribe(track))
            elif track.kind == "video":
                # Use local video if available, otherwise echo back
                if local_video:
                    pc.addTrack(local_video)
                else:
                    pc.addTrack(relay.subscribe(track))
        
        # Handle the offer
        await pc.setRemoteDescription(offer)
        
        # Create answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        return web.json_response({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    except Exception as e:
        print(f"Error handling offer: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=400)


async def on_shutdown(app):
    """Close peer connections and recorders on shutdown"""
    # Close peer connections
    coros = [pc.close() for pc in pcs]
    
    # Close recorders
    for user_id, recorder in recorders.items():
        if recorder.started:
            coros.append(recorder.stop())
    
    await asyncio.gather(*coros)
    pcs.clear()
    recorders.clear()


def create_app():
    """Create the web application"""
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    
    # Add routes
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    app.router.add_static("/static/", path=os.path.join(os.path.dirname(__file__), "static"))
    
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8080)

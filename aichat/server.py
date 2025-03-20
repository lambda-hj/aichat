import asyncio
import datetime
import os
import uuid
import wave
from pathlib import Path
from typing import Dict, Optional

import av
import cv2
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaRecorder, MediaRelay

# Paths for storing recordings
AUDIO_ROOT = Path(__file__).parent / "recordings" / "audio"
VIDEO_ROOT = Path(__file__).parent / "recordings" / "video"

# Ensure directories exist
AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
VIDEO_ROOT.mkdir(parents=True, exist_ok=True)

# Store active peer connections
pcs = set()
relay = MediaRelay()

class AudioTrackProcessor(MediaStreamTrack):
    """
    A track that receives an audio track and saves it to disk.
    """
    kind = "audio"

    def __init__(self, track, user_id):
        super().__init__()
        self.track = track
        self.user_id = user_id
        self.audio_file = None
        self.sample_rate = 48000
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = f"{self.user_id}_{self.timestamp}.wav"
        self.filepath = AUDIO_ROOT / self.filename
        
        # Create WAV file
        self.audio_file = wave.open(str(self.filepath), "wb")
        self.audio_file.setnchannels(1)  # Mono
        self.audio_file.setsampwidth(2)  # 16-bit
        self.audio_file.setframerate(self.sample_rate)
        
        print(f"Audio recording started: {self.filepath}")

    async def recv(self):
        try:
            frame = await self.track.recv()
            
            # Save audio data to file
            if self.audio_file:
                # Get the frame's sample rate
                frame_sample_rate = getattr(frame, 'sample_rate', self.sample_rate)
                
                # Try to convert any format to audio data
                if frame.format.name == "s16":
                    # Direct conversion for s16 format
                    audio_data = frame.to_ndarray()
                    
                    # Resample if needed
                    if frame_sample_rate != self.sample_rate:
                        print(f"Resampling audio from {frame_sample_rate}Hz to {self.sample_rate}Hz")
                        # Simple resampling approach - convert the audio data to the right format
                        # This preserves the pitch by adjusting the data length
                        resampled_data = self._resample_audio(audio_data, frame_sample_rate, self.sample_rate)
                        sound_data = bytes(resampled_data.tobytes())
                    else:
                        sound_data = bytes(audio_data.tobytes())
                    
                    self.audio_file.writeframes(sound_data)
                elif hasattr(frame, 'to_ndarray'):
                    # Try to convert other formats
                    try:
                        # Convert to s16 format if possible
                        audio_data = frame.to_ndarray()
                        
                        # Resample if needed
                        if frame_sample_rate != self.sample_rate:
                            print(f"Resampling audio from {frame_sample_rate}Hz to {self.sample_rate}Hz")
                            resampled_data = self._resample_audio(audio_data, frame_sample_rate, self.sample_rate)
                            sound_data = bytes(resampled_data.tobytes())
                        else:
                            sound_data = bytes(audio_data.tobytes())
                        
                        self.audio_file.writeframes(sound_data)
                    except Exception as e:
                        print(f"Could not convert audio frame: {e}")
            
            return frame
        except Exception as e:
            print(f"Error in audio processing: {e}")
            # Return the original frame or an empty one if needed
            if 'frame' in locals():
                return frame
            else:
                from av import AudioFrame
                return AudioFrame.empty()
    
    def stop(self):
        try:
            if self.audio_file:
                self.audio_file.close()
                print(f"Audio recording stopped: {self.filepath}")
                self.audio_file = None
        except Exception as e:
            print(f"Error stopping audio recording: {e}")
            self.audio_file = None
            
    def _resample_audio(self, audio_data, src_rate, dst_rate):
        """
        Resample audio data from source rate to destination rate.
        This is a simple implementation to correct pitch issues.
        
        Args:
            audio_data: The audio data as numpy array
            src_rate: Source sample rate
            dst_rate: Destination sample rate
            
        Returns:
            Resampled audio data as numpy array
        """
        try:
            import numpy as np
            from scipy import signal
            
            # Calculate number of samples for target rate
            n_samples = int(len(audio_data) * dst_rate / src_rate)
            
            # Resample using scipy's resample function
            resampled = signal.resample(audio_data, n_samples)
            return resampled
        except ImportError:
            print("Could not import scipy for proper resampling. Using basic method.")
            # Fallback to a very basic resampling method if scipy is not available
            # This isn't ideal but better than nothing
            ratio = dst_rate / src_rate
            import numpy as np
            
            # Basic resampling by linear interpolation
            indices = np.round(np.linspace(0, len(audio_data) - 1, int(len(audio_data) * ratio))).astype(int)
            return audio_data[indices]


class VideoTrackProcessor(MediaStreamTrack):
    """
    A track that receives a video track and saves it to disk.
    """
    kind = "video"

    def __init__(self, track, user_id):
        super().__init__()
        self.track = track
        self.user_id = user_id
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Change to .avi for better codec compatibility
        self.filename = f"{self.user_id}_{self.timestamp}.avi"
        self.filepath = VIDEO_ROOT / self.filename
        
        # Create video writer
        self.writer = None
        self.frame_size = None
        
        print(f"Video recording prepared: {self.filepath}")

    async def recv(self):
        try:
            frame = await self.track.recv()
            
            # Initialize video writer on first frame
            if self.writer is None and frame.width and frame.height:
                self.frame_size = (frame.width, frame.height)
                
                # Try different codecs in order of preference
                # Change file extension to .avi for better compatibility
                self.filepath = self.filepath.with_suffix('.avi')
                
                # Try XVID codec (more widely supported)
                self.writer = cv2.VideoWriter(
                    str(self.filepath),
                    cv2.VideoWriter_fourcc(*'XVID'),
                    30.0,  # FPS
                    self.frame_size
                )
                
                # Verify the writer opened successfully
                if not self.writer.isOpened():
                    # Fallback to mp4v if XVID failed
                    self.writer = cv2.VideoWriter(
                        str(self.filepath),
                        cv2.VideoWriter_fourcc(*'mp4v'),
                        30.0,  # FPS
                        self.frame_size
                    )
                
                # Final check if writer is opened
                if self.writer.isOpened():
                    print(f"Video recording started: {self.filepath}")
                else:
                    print(f"Failed to initialize video writer for: {self.filepath}")
            
            # Save video frame
            if self.writer and self.writer.isOpened():
                try:
                    # Convert frame to BGR format for OpenCV
                    img = frame.to_ndarray(format="bgr24")
                    self.writer.write(img)
                except Exception as e:
                    print(f"Error writing video frame: {e}")
            
            return frame
        except Exception as e:
            print(f"Error in video processing: {e}")
            # Return the original frame or an empty one if needed
            if 'frame' in locals():
                return frame
            else:
                from av import VideoFrame
                return VideoFrame.empty()
    
    def stop(self):
        try:
            if self.writer:
                self.writer.release()
                print(f"Video recording stopped: {self.filepath}")
                self.writer = None
        except Exception as e:
            print(f"Error stopping video recording: {e}")
            self.writer = None


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
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    # Generate a unique ID for this user session
    user_id = str(uuid.uuid4())
    
    # Create a new peer connection
    pc = RTCPeerConnection()
    pcs.add(pc)
    
    # Track processors
    audio_processor = None
    video_processor = None
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            
            # Stop recording
            if audio_processor:
                audio_processor.stop()
            if video_processor:
                video_processor.stop()
    
    @pc.on("track")
    def on_track(track):
        print(f"Track {track.kind} received")
        
        nonlocal audio_processor, video_processor
        
        if track.kind == "audio":
            audio_processor = AudioTrackProcessor(relay.subscribe(track), user_id)
            pc.addTrack(audio_processor)
        elif track.kind == "video":
            video_processor = VideoTrackProcessor(relay.subscribe(track), user_id)
            pc.addTrack(video_processor)
    
    # Handle the offer
    await pc.setRemoteDescription(offer)
    
    # Create answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    return web.json_response({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    })


async def on_shutdown(app):
    """Close peer connections on shutdown"""
    # Close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


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

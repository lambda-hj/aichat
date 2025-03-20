// WebRTC client for audio/video recording

// Global variables
let pc = null;
let localStream = null;
const startButton = document.getElementById('startButton');
const stopButton = document.getElementById('stopButton');
const localVideo = document.getElementById('localVideo');
const statusDiv = document.getElementById('status');

// Set up event listeners
startButton.addEventListener('click', start);
stopButton.addEventListener('click', stop);

// Start WebRTC connection
async function start() {
    try {
        // Check if we're running in a secure context
        if (!window.isSecureContext) {
            console.warn('getUserMedia requires a secure context (HTTPS or localhost)');
            // Continue anyway as we might be on localhost which is considered secure
        }
        
        // Check if mediaDevices is supported and provide polyfill if needed
        if (!navigator.mediaDevices) {
            console.warn('MediaDevices API not directly supported, creating polyfill');
            navigator.mediaDevices = {};
        }
        
        // Polyfill getUserMedia based on Chrome developer documentation
        if (!navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia = function(constraints) {
                // Get the legacy API versions if they exist
                const getUserMedia = navigator.webkitGetUserMedia ||
                                     navigator.mozGetUserMedia ||
                                     navigator.msGetUserMedia;
                
                // If no legacy API exists, return a rejected promise
                if (!getUserMedia) {
                    console.error('No getUserMedia implementation available in this browser');
                    const error = new Error('getUserMedia is not supported in this browser');
                    error.name = 'NotSupportedError';
                    return Promise.reject(error);
                }
                
                // Wrap the legacy API in a Promise
                return new Promise(function(resolve, reject) {
                    try {
                        getUserMedia.call(navigator, 
                            constraints,
                            function(stream) { resolve(stream); },
                            function(err) { reject(err); }
                        );
                    } catch (e) {
                        reject(e);
                    }
                });
            };
        }
        
        // Add enumerateDevices polyfill if needed
        if (!navigator.mediaDevices.enumerateDevices) {
            navigator.mediaDevices.enumerateDevices = function() {
                return Promise.resolve([]);
            };
        }
        
        try {
            // Try to get both audio and video
            localStream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 }
                }
            });
            console.log("Successfully got audio and video tracks");
        } catch (e) {
            console.warn("Could not get both audio and video: " + e.message);
            try {
                // Fall back to just audio if video fails
                localStream = await navigator.mediaDevices.getUserMedia({
                    audio: true,
                    video: false
                });
                console.log("Using audio only");
            } catch (audioError) {
                console.warn("Could not get audio: " + audioError.message);
                // Last resort - create empty stream with no tracks
                localStream = new MediaStream();
                console.log("Using empty media stream - will use synthetic media from server");
                
                // Add a dummy audio track to the stream
                try {
                    // Create an audio context and oscillator for a dummy audio track
                    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    const oscillator = audioCtx.createOscillator();
                    const dst = audioCtx.createMediaStreamDestination();
                    oscillator.connect(dst);
                    oscillator.start();
                    const dummyAudioTrack = dst.stream.getAudioTracks()[0];
                    localStream.addTrack(dummyAudioTrack);
                    console.log("Added dummy audio track");
                } catch (dummyError) {
                    console.warn("Could not create dummy audio track: " + dummyError.message);
                }
            }
        }

        // Display local video
        localVideo.srcObject = localStream;

        // Create peer connection
        pc = new RTCPeerConnection({
            sdpSemantics: 'unified-plan',
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        // Add local tracks to peer connection (if any)
        const tracks = localStream.getTracks();
        if (tracks.length > 0) {
            tracks.forEach(track => {
                pc.addTrack(track, localStream);
            });
        } else {
            console.warn("No local tracks available, server will use synthetic media");
            // Create a dummy data channel to establish connection
            pc.createDataChannel("dummy");
        }

        // Create offer
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Send offer to server
        const response = await fetch('/offer', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type
            })
        });

        // Get answer from server
        try {
            const answer = await response.json();
            
            // Check if server returned an error
            if (answer.error) {
                throw new Error(answer.error);
            }
            
            await pc.setRemoteDescription(new RTCSessionDescription(answer));
            
            // Update UI
            startButton.disabled = true;
            stopButton.disabled = false;
            statusDiv.textContent = 'Status: Connected - Recording in progress';
            statusDiv.className = 'status connected';
        } catch (e) {
            throw new Error(`Failed to parse SessionDescription: ${e.message}`);
        }

        // Monitor connection state
        pc.addEventListener('connectionstatechange', () => {
            if (pc.connectionState === 'disconnected' || 
                pc.connectionState === 'failed' || 
                pc.connectionState === 'closed') {
                stop();
            }
        });

    } catch (error) {
        console.error('Error starting WebRTC connection:', error);
        const errorMessage = error.name === 'NotSupportedError' 
            ? 'Media API not supported in this browser. Please try Chrome, Firefox, or Edge.'
            : error.message;
        statusDiv.textContent = `Status: Error - ${errorMessage}`;
        statusDiv.className = 'status disconnected';
    }
}

// Stop WebRTC connection
function stop() {
    if (pc) {
        // Close peer connection
        pc.close();
        pc = null;
    }

    // Stop all tracks in local stream
    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
    }

    // Clear video
    localVideo.srcObject = null;

    // Update UI
    startButton.disabled = false;
    stopButton.disabled = true;
    statusDiv.textContent = 'Status: Disconnected';
    statusDiv.className = 'status disconnected';
}

// Handle page unload
window.addEventListener('beforeunload', () => {
    stop();
});

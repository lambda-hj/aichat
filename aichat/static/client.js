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
        
        localStream = await navigator.mediaDevices.getUserMedia({
            audio: true,
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 }
            }
        });

        // Display local video
        localVideo.srcObject = localStream;

        // Create peer connection
        pc = new RTCPeerConnection({
            sdpSemantics: 'unified-plan',
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        // Add local tracks to peer connection
        localStream.getTracks().forEach(track => {
            pc.addTrack(track, localStream);
        });

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
        const answer = await response.json();
        await pc.setRemoteDescription(answer);

        // Update UI
        startButton.disabled = true;
        stopButton.disabled = false;
        statusDiv.textContent = 'Status: Connected - Recording in progress';
        statusDiv.className = 'status connected';

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
        statusDiv.textContent = `Status: Error - ${error.message}`;
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

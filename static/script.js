// Get URL parameters
const urlParams = new URLSearchParams(window.location.search);
const roomId = urlParams.get('room') || window.location.pathname.split('/').pop();
const displayName = urlParams.get('name') || `User-${Math.random().toString(36).substr(2, 4)}`;
const userId = urlParams.get('userId');

// Try to get user info from localStorage if available
let storedUserInfo = null;
try {
  const stored = localStorage.getItem('meetUserInfo');
  if (stored) {
    storedUserInfo = JSON.parse(stored);
  }
} catch (e) {
  console.warn('Could not parse stored user info:', e);
}

console.log('Initializing with:', { roomId, displayName, userId, storedUserInfo });

// DOM elements
const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");
const remoteVideosContainer = document.getElementById("remoteVideos");
const micBtn = document.getElementById("micBtn");
const videoBtn = document.getElementById("videoBtn");
const leaveBtn = document.getElementById("leaveBtn");
const participantsList = document.getElementById("participantsList");
const loadingScreen = document.getElementById("loadingScreen");

// WebRTC Configuration
const configuration = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun2.l.google.com:19302' }
  ]
};

// Global variables
let ws = null;
let localStream = null;
let userInfo = storedUserInfo || null;
let peerConnections = new Map(); // {remoteUserId: RTCPeerConnection}
let remoteStreams = new Map(); // {remoteUserId: MediaStream}
let isMicOn = true;
let isVideoOn = true;
let isInitialized = false;
let recorderPeer = null;

// Show loading screen
function showLoading(message = 'Joining meeting...') {
  if (loadingScreen) {
    loadingScreen.querySelector('div:last-child').textContent = message;
    loadingScreen.style.display = 'flex';
  }
}

// Hide loading screen
function hideLoading() {
  if (loadingScreen) {
    loadingScreen.style.display = 'none';
  }
}

// Show error and redirect
function showErrorAndRedirect(message, redirectDelay = 3000) {
  alert(message);
  setTimeout(() => {
    window.location.href = '/join';
  }, redirectDelay);
}

// Initialize the application
async function initialize() {
  if (isInitialized) return;

  try {
    console.log(`Initializing room: ${roomId}, display name: ${displayName}`);
    showLoading('Setting up camera and microphone...');

    // Validate required parameters
    if (!roomId || roomId === 'undefined') {
      throw new Error('Room ID is required');
    }

    if (!displayName || displayName === 'undefined') {
      throw new Error('Display name is required');
    }

    // Step 1: Get user media first
    await getUserMedia();

    showLoading('Connecting to room...');

    // Step 2: Join room via API if we don't have user info
    if (!userInfo || !userInfo.user_id) {
      await joinRoomAPI();
    }

    showLoading('Establishing connection...');

    // Step 3: Connect to WebSocket
    try {
    await connectWebSocket();
    try {
      await startRecorderPeer();
    } catch (err) {
      console.warn('Failed to start recorder peer on init:', err);
    }
    hideLoading();
    isInitialized = true;
    console.log('Initialization complete');
    }
    catch (err) {
      console.warn('Failed to connect web socket peer on init:', err);
    }
  } catch (error) {
    console.error('Initialization failed:', error);
    hideLoading();
    showErrorAndRedirect(`Failed to join meeting: ${error.message}`);
  }
}

// Get user media
async function getUserMedia() {
  try {
    localStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280, max: 1920 },
        height: { ideal: 720, max: 1080 }
      },
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    if (localVideo) {
      localVideo.srcObject = localStream;
    }
    console.log('Local media initialized');
  } catch (error) {
    console.error('Error accessing media devices:', error);

    // Try with lower quality settings
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
        audio: true
      });

      if (localVideo) {
        localVideo.srcObject = localStream;
      }
      console.log('Local media initialized with fallback settings');
    } catch (fallbackError) {
      throw new Error('Could not access camera/microphone. Please check permissions and ensure no other application is using them.');
    }
  }
}

// Join room via API
async function joinRoomAPI() {
  try {
    const response = await fetch(`/api/rooms/${roomId}/join`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        display_name: displayName
      })
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('Room not found. The room may have ended or the code is incorrect.');
      } else if (response.status === 400) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Room is full or no longer accepting participants.');
      } else {
        throw new Error('Failed to join room. Please try again.');
      }
    }

    userInfo = await response.json();
    console.log('Joined room successfully:', userInfo);

    // Update UI with room info
    if (document.querySelector('.meeting-title')) {
      document.querySelector('.meeting-title').textContent = `Room: ${roomId}`;
    }

  } catch (error) {
    console.error('Error joining room:', error);
    throw error;
  }
}
// NEW CODE: Start a hidden PeerConnection that sends local tracks to backend for recording
async function startRecorderPeer() {
  if (!localStream) {
    console.warn('startRecorderPeer: localStream not ready');
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn('startRecorderPeer: websocket not open yet');
    return;
  }

  try {
    // If already started, return
    if (recorderPeer) {
      console.log('Recorder peer already running');
      return;
    }

    recorderPeer = new RTCPeerConnection(configuration);

    // Add local tracks to recorder peer
    localStream.getTracks().forEach(track => {
      recorderPeer.addTrack(track, localStream);
    });

    // Send ICE candidates from recorder peer to backend
    recorderPeer.onicecandidate = (event) => {
      if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'recorder-ice-candidate',
          candidate: event.candidate
        }));
      }
    };

    recorderPeer.onconnectionstatechange = () => {
      console.log('Recorder PC connectionState:', recorderPeer.connectionState);
      // optional: if closed/failed, cleanup
      if (recorderPeer.connectionState === 'failed' || recorderPeer.connectionState === 'closed') {
        // we'll let cleanup() handle removal
      }
    };

    // If tracks are added/removed later (e.g., start screen share), renegotiation may be needed
    recorderPeer.onnegotiationneeded = async () => {
      try {
        const offer = await recorderPeer.createOffer();
        await recorderPeer.setLocalDescription(offer);
        ws.send(JSON.stringify({
          type: 'recorder-offer',
          sdp: offer.sdp,
          sdpType: offer.type
        }));
      } catch (err) {
        console.warn('Recorder renegotiation failed', err);
      }
    };

    // Create initial offer and send to backend via your signaling WebSocket
    const offer = await recorderPeer.createOffer({ offerToReceiveAudio: false, offerToReceiveVideo: false });
    await recorderPeer.setLocalDescription(offer);

    ws.send(JSON.stringify({
      type: 'recorder-offer',
      sdp: offer.sdp,
      sdpType: offer.type
    }));

    console.log('Recorder peer started and offer sent');
  } catch (err) {
    console.error('startRecorderPeer error:', err);
    // Cleanup partial peer if something failed
    try { recorderPeer && recorderPeer.close(); } catch (e) {}
    recorderPeer = null;
  }
}

// MODIFY THIS FUNCTION - THE KEY FIX FOR PRODUCTION
async function connectWebSocket() {
  return new Promise((resolve, reject) => {
    if (!userInfo || !userInfo.user_id) {
      reject(new Error('User info not available'));
      return;
    }

    // ENHANCED URL CONSTRUCTION FOR PRODUCTION
    let wsUrl;

    // Check if we're in a development environment
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      // Development
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      wsUrl = `${protocol}//${host}/ws/${roomId}/${userInfo.user_id}`;
    } else {
      // Production - force WSS if HTTPS, otherwise use current protocol
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      wsUrl = `${protocol}//${host}/ws/${roomId}/${userInfo.user_id}`;
    }

    console.log('Connecting to WebSocket:', wsUrl);

    // ADD CONNECTION TIMEOUT AND RETRY LOGIC
    let connectionTimeout = setTimeout(() => {
      console.error('WebSocket connection timeout');
      reject(new Error('Connection timeout - please check your internet connection'));
    }, 15000); // 15 second timeout

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected successfully');
      clearTimeout(connectionTimeout);
      resolve();
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      clearTimeout(connectionTimeout);

      // More specific error handling
      if (ws.readyState === WebSocket.CLOSED) {
        reject(new Error('WebSocket connection failed - server may be unavailable'));
      } else {
        reject(new Error('WebSocket connection error'));
      }
    };

    ws.onmessage = handleWebSocketMessage;
    ws.onclose = handleWebSocketClose;
  });
}

// Handle WebSocket messages
async function handleWebSocketMessage(event) {
  try {
    const message = JSON.parse(event.data);
    console.log('Received message:', message.type, message);

    switch (message.type) {
      case 'room-joined':
        await handleRoomJoined(message);
        break;

      case 'new-user-joined':
        await handleNewUserJoined(message);
        break;

      case 'user-left':
        handleUserLeft(message);
        break;

      case 'webrtc-offer':
        await handleWebRTCOffer(message);
        break;

      case 'webrtc-answer':
        await handleWebRTCAnswer(message);
        break;

      case 'ice-candidate':
        await handleIceCandidate(message);
        break;

      case 'user-media-changed':
        handleUserMediaChanged(message);
        break;

      case 'room-ended':
        handleRoomEnded(message);
        break;

      case 'error':
        console.error('Server error:', message.message);
        break;
            case 'recorder-answer':
        // Server answered our recorder offer with its SDP
        try {
          if (recorderPeer) {
            await recorderPeer.setRemoteDescription(new RTCSessionDescription({
              type: message.sdpType || 'answer',
              sdp: message.sdp
            }));
          } else {
            console.warn('recorder-answer received but recorderPeer is null');
          }
        } catch (err) {
          console.error('Error applying recorder answer:', err);
        }
        break;

      case 'recorder-ice-candidate':
        // (optional) server might send back ICE candidates for recorder peer
        try {
          if (recorderPeer && message.candidate) {
            await recorderPeer.addIceCandidate(new RTCIceCandidate(message.candidate));
          }
        } catch (err) {
          console.warn('Error adding recorder ICE candidate:', err);
        }
        break;

      default:
        console.log('Unknown message type:', message.type);
    }
  } catch (error) {
    console.error('Error handling WebSocket message:', error);
  }
}

// Handle room joined
async function handleRoomJoined(message) {
  console.log(`Joined room with ${message.existing_users.length} existing users`);

  // Update participants list
  const allParticipants = [
    {
      user_id: userInfo.user_id,
      display_name: `${displayName} (You)`,
      audio_enabled: isMicOn,
      video_enabled: isVideoOn
    },
    ...message.existing_users
  ];
  updateParticipantsList(allParticipants);

  // Create peer connections to existing users and send offers
  for (const user of message.existing_users) {
    await createPeerConnection(user.user_id);
    await sendOffer(user.user_id);
  }
}

// Handle new user joined
async function handleNewUserJoined(message) {
  console.log('New user joined:', message.new_user);

  // Add to participants list
  addParticipantToList(message.new_user);

  // Create peer connection (they will send us an offer)
  await createPeerConnection(message.new_user.user_id);
}

// Handle user left
function handleUserLeft(message) {
  console.log('User left:', message.user_id);

  // Clean up peer connection
  if (peerConnections.has(message.user_id)) {
    peerConnections.get(message.user_id).close();
    peerConnections.delete(message.user_id);
  }

  // Remove remote stream
  if (remoteStreams.has(message.user_id)) {
    remoteStreams.delete(message.user_id);
  }

  // Remove from UI
  removeParticipantFromList(message.user_id);
  removeRemoteVideo(message.user_id);
}

// Create peer connection for a remote user
async function createPeerConnection(remoteUserId) {
  console.log(`Creating peer connection for user: ${remoteUserId}`);

  const pc = new RTCPeerConnection(configuration);

  // Add local stream tracks
  if (localStream) {
    localStream.getTracks().forEach(track => {
      pc.addTrack(track, localStream);
    });
  }

  // Handle remote stream
  pc.ontrack = (event) => {
    console.log(`Received remote stream from user: ${remoteUserId}`);
    if (event.streams && event.streams[0]) {
      remoteStreams.set(remoteUserId, event.streams[0]);
      displayRemoteVideo(remoteUserId, event.streams[0]);
    }
  };

  // Handle ICE candidates
  pc.onicecandidate = (event) => {
    if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {
      console.log(`Sending ICE candidate to user: ${remoteUserId}`);
      ws.send(JSON.stringify({
        type: 'ice-candidate',
        to_user: remoteUserId,
        data: event.candidate
      }));
    }
  };

  // Handle connection state changes
  pc.onconnectionstatechange = () => {
    console.log(`Connection state with ${remoteUserId}:`, pc.connectionState);
    if (pc.connectionState === 'failed') {
      console.log(`Connection failed with ${remoteUserId}, cleaning up`);
      // Clean up failed connection
      if (peerConnections.has(remoteUserId)) {
        peerConnections.get(remoteUserId).close();
        peerConnections.delete(remoteUserId);
      }
      removeRemoteVideo(remoteUserId);
    }
  };

  peerConnections.set(remoteUserId, pc);
}

// Send offer to remote user
async function sendOffer(remoteUserId) {
  try {
    console.log(`Sending offer to user: ${remoteUserId}`);
    const pc = peerConnections.get(remoteUserId);

    if (!pc) {
      console.error(`No peer connection found for user: ${remoteUserId}`);
      return;
    }

    const offer = await pc.createOffer({
      offerToReceiveAudio: true,
      offerToReceiveVideo: true
    });

    await pc.setLocalDescription(offer);

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'webrtc-offer',
        to_user: remoteUserId,
        data: offer
      }));
    }
  } catch (error) {
    console.error(`Error sending offer to ${remoteUserId}:`, error);
  }
}

// Handle WebRTC offer
async function handleWebRTCOffer(message) {
  try {
    console.log(`Handling offer from user: ${message.from_user}`);
    const pc = peerConnections.get(message.from_user);

    if (!pc) {
      console.error(`No peer connection found for user: ${message.from_user}`);
      return;
    }

    await pc.setRemoteDescription(new RTCSessionDescription(message.data));

    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'webrtc-answer',
        to_user: message.from_user,
        data: answer
      }));
    }
  } catch (error) {
    console.error(`Error handling offer from ${message.from_user}:`, error);
  }
}

// Handle WebRTC answer
async function handleWebRTCAnswer(message) {
  try {
    console.log(`Handling answer from user: ${message.from_user}`);
    const pc = peerConnections.get(message.from_user);

    if (!pc) {
      console.error(`No peer connection found for user: ${message.from_user}`);
      return;
    }

    await pc.setRemoteDescription(new RTCSessionDescription(message.data));
  } catch (error) {
    console.error(`Error handling answer from ${message.from_user}:`, error);
  }
}

// Handle ICE candidate
async function handleIceCandidate(message) {
  try {
    console.log(`Adding ICE candidate from user: ${message.from_user}`);
    const pc = peerConnections.get(message.from_user);

    if (!pc) {
      console.error(`No peer connection found for user: ${message.from_user}`);
      return;
    }

    await pc.addIceCandidate(new RTCIceCandidate(message.data));
  } catch (error) {
    console.error(`Error adding ICE candidate from ${message.from_user}:`, error);
  }
}

// Handle user media changed
function handleUserMediaChanged(message) {
  console.log(`User ${message.user_id} media changed:`, message);
  updateParticipantMediaStatus(message.user_id, message.audio_enabled, message.video_enabled);
}

// Handle room ended
function handleRoomEnded(message) {
  alert(message.message || 'Room has been ended');
  cleanup();
  window.location.href = '/join';
}

// MODIFY WEBSOCKET CLOSE HANDLER FOR BETTER RECONNECTION
function handleWebSocketClose(event) {
  console.log('WebSocket connection closed:', event.code, event.reason);

  if (!isInitialized) return;

  // Attempt to reconnect if the close was unexpected
  if (event.code !== 1000 && event.code !== 1001) {
    console.log('Attempting to reconnect...');
    showLoading('Connection lost, reconnecting...');

    setTimeout(async () => {
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        try {
          await connectWebSocket();
          hideLoading();
          console.log('Reconnected successfully');
        } catch (error) {
          console.error('Reconnection failed:', error);
          hideLoading();
          showErrorAndRedirect('Connection lost. Redirecting to join page...');
        }
      }
    }, 2000);
  }
}

// Display remote video
function displayRemoteVideo(userId, stream) {
  // Remove existing video if any
  removeRemoteVideo(userId);

  // For the first remote user, use the existing remoteVideo element
  if (remoteStreams.size === 1 && remoteVideo && !remoteVideo.srcObject) {
    remoteVideo.srcObject = stream;
    remoteVideo.style.display = 'block';
    const label = remoteVideo.parentElement.querySelector('.video-label');
    if (label) {
      // Get display name from participants list
      const participant = Array.from(document.querySelectorAll('.participant')).find(p =>
        p.id === `participant-${userId}`
      );
      if (participant) {
        const name = participant.querySelector('.participant-name').textContent;
        label.textContent = name.replace(' (You)', '');
      } else {
        label.textContent = `User ${userId}`;
      }
    }
    console.log(`Added first remote video for user: ${userId}`);
    return;
  }

  // For additional users, create new video elements
  const videoContainer = document.createElement('div');
  videoContainer.className = 'video-container';
  videoContainer.id = `container-${userId}`;

  const videoElement = document.createElement('video');
  videoElement.id = `remoteVideo-${userId}`;
  videoElement.autoplay = true;
  videoElement.playsinline = true;
  videoElement.srcObject = stream;

  const labelElement = document.createElement('div');
  labelElement.className = 'video-label';

  // Get display name from participants list
  const participant = Array.from(document.querySelectorAll('.participant')).find(p =>
    p.id === `participant-${userId}`
  );
  if (participant) {
    const name = participant.querySelector('.participant-name').textContent;
    labelElement.textContent = name.replace(' (You)', '');
  } else {
    labelElement.textContent = `User ${userId}`;
  }

  videoContainer.appendChild(videoElement);
  videoContainer.appendChild(labelElement);

  if (remoteVideosContainer) {
    remoteVideosContainer.appendChild(videoContainer);
  }

  console.log(`Added additional remote video for user: ${userId}`);
}

// Remove remote video
function removeRemoteVideo(userId) {
  // Check if it's the main remote video
  if (remoteVideo && remoteVideo.srcObject && remoteStreams.has(userId)) {
    const stream = remoteStreams.get(userId);
    if (remoteVideo.srcObject === stream) {
      remoteVideo.srcObject = null;
      remoteVideo.style.display = 'none';
      const label = remoteVideo.parentElement.querySelector('.video-label');
      if (label) {
        label.textContent = 'Remote User';
      }
      console.log(`Removed main remote video for user: ${userId}`);
      return;
    }
  }

  // Check additional video containers
  const container = document.getElementById(`container-${userId}`);
  if (container) {
    container.remove();
    console.log(`Removed additional remote video for user: ${userId}`);
  }
}

// Update participants list
function updateParticipantsList(participants) {
  if (!participantsList) return;

  participantsList.innerHTML = '<h3>Participants</h3>';

  participants.forEach(participant => {
    addParticipantToList(participant);
  });
}

// Add participant to list
function addParticipantToList(participant) {
  if (!participantsList) return;

  // Don't duplicate participants
  const existing = document.getElementById(`participant-${participant.user_id}`);
  if (existing) {
    return;
  }

  const participantDiv = document.createElement('div');
  participantDiv.id = `participant-${participant.user_id}`;
  participantDiv.className = 'participant';
  participantDiv.innerHTML = `
    <span class="participant-name">${participant.display_name}</span>
    <span class="participant-status">
      ${participant.audio_enabled ? '🎤' : '🔇'}
      ${participant.video_enabled ? '📷' : '📷❌'}
    </span>
  `;

  participantsList.appendChild(participantDiv);
}

// Remove participant from list
function removeParticipantFromList(userId) {
  const participantElement = document.getElementById(`participant-${userId}`);
  if (participantElement) {
    participantElement.remove();
  }
}

// Update participant media status
function updateParticipantMediaStatus(userId, audioEnabled, videoEnabled) {
  const participantElement = document.getElementById(`participant-${userId}`);
  if (participantElement) {
    const statusElement = participantElement.querySelector('.participant-status');
    if (statusElement) {
      statusElement.innerHTML = `
        ${audioEnabled ? '🎤' : '🔇'}
        ${videoEnabled ? '📷' : '📷❌'}
      `;
    }
  }
}

// Media controls
if (micBtn) {
  micBtn.onclick = async () => {
    if (localStream) {
      const audioTrack = localStream.getAudioTracks()[0];
      if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled;
        isMicOn = audioTrack.enabled;
        micBtn.style.backgroundColor = isMicOn ? '#5f6368' : '#ea4335';
        micBtn.textContent = isMicOn ? '🎤' : '🔇';
        console.log('Microphone:', isMicOn ? 'ON' : 'OFF');

        // Update own participant status
        updateParticipantMediaStatus(userInfo?.user_id, isMicOn, isVideoOn);

        // Notify server
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'media-toggle',
            audio_enabled: isMicOn,
            video_enabled: isVideoOn
          }));
        }

        // Update API
        await updateMediaStatusAPI();
      }
    }
  };
}

if (videoBtn) {
  videoBtn.onclick = async () => {
    if (localStream) {
      const videoTrack = localStream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.enabled = !videoTrack.enabled;
        isVideoOn = videoTrack.enabled;
        videoBtn.style.backgroundColor = isVideoOn ? '#5f6368' : '#ea4335';
        videoBtn.textContent = isVideoOn ? '📷' : '📷❌';
        console.log('Video:', isVideoOn ? 'ON' : 'OFF');

        // Update own participant status
        updateParticipantMediaStatus(userInfo?.user_id, isMicOn, isVideoOn);

        // Notify server
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'media-toggle',
            audio_enabled: isMicOn,
            video_enabled: isVideoOn
          }));
        }

        // Update API
        await updateMediaStatusAPI();
      }
    }
  };
}

if (leaveBtn) {
  leaveBtn.onclick = () => {
    cleanup();
    window.location.href = '/join';
  };
}

// Update media status via API
async function updateMediaStatusAPI() {
  if (!userInfo || !userInfo.user_id) return;

  try {
    await fetch(`/api/rooms/${roomId}/users/${userInfo.user_id}/media`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        audio_enabled: isMicOn,
        video_enabled: isVideoOn
      })
    });
  } catch (error) {
    console.error('Error updating media status:', error);
  }
}

// Cleanup function
function cleanup() {
  console.log('Cleaning up resources...');
    // NEW CODE: close recorder peer if running
  if (recorderPeer) {
    try {
      recorderPeer.close();
    } catch (e) {
      console.warn('Error closing recorderPeer:', e);
    }
    recorderPeer = null;
  }

  if (localStream) {
    localStream.getTracks().forEach(track => {
      track.stop();
      console.log('Stopped track:', track.kind);
    });
    localStream = null;
  }
  if (localStream) {
    localStream.getTracks().forEach(track => {
      track.stop();
      console.log('Stopped track:', track.kind);
    });
    localStream = null;
  }

  peerConnections.forEach((pc, userId) => {
    console.log(`Closing peer connection for user: ${userId}`);
    pc.close();
  });
  peerConnections.clear();
  remoteStreams.clear();

  if (ws) {
    ws.close(1000, 'User left');
    ws = null;
  }

  // Clear localStorage
  localStorage.removeItem('meetUserInfo');
}

// Initialize when page loads
window.addEventListener('load', () => {
  // Small delay to ensure DOM is fully loaded
  setTimeout(initialize, 100);
});

// Handle page unload
window.addEventListener('beforeunload', cleanup);

// Handle page visibility changes
document.addEventListener('visibilitychange', () => {
      if (ws && ws.readyState === WebSocket.CLOSED) {
        console.log('Page visible, attempting reconnection...');
        connectWebSocket()
          .then(() => startRecorderPeer().catch(e => console.warn('recorder restart failed:', e)))
          .catch(error => {
            console.error('Reconnection failed:', error);
          });
      }

});
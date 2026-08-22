export interface CVWorkerMessage {
  type: 'init' | 'process_frame' | 'stop';
  sessionId?: string;
  imageData?: ImageData;
  backendUrl?: string;
}

export interface CVWorkerResult {
  type: 'initialized' | 'frame_result' | 'error';
  result?: {
    hasFace: boolean;
    focusScore: number;
    engagementScore: number;
    presence: string;
    isDistracted: boolean;
    warning?: string;
  };
  error?: string;
}

let ws: WebSocket | null = null;
let currentSessionId: string | null = null;

function connectWebSocket(backendUrl: string, sessionId: string) {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  
  const url = `${backendUrl.replace(/^http/, 'ws')}/api/v1/monitoring/session/${sessionId}`;
  ws = new WebSocket(url);
  
  ws.onopen = () => {
    postMessage({ type: 'initialized' } as CVWorkerResult);
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      postMessage({
        type: 'frame_result',
        result: data
      } as CVWorkerResult);
    } catch (e) {
      console.error('Failed to parse backend CV message', e);
    }
  };
  
  ws.onerror = (error) => {
    postMessage({
      type: 'error',
      error: 'WebSocket connection error'
    } as CVWorkerResult);
  };
  
  ws.onclose = () => {
    ws = null;
  };
}

function processFrame(imageData: ImageData) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    // Basic fallback analysis if not connected
    const data = imageData.data;
    let brightness = 0;
    // Simple pixel sampling to avoid iterating all pixels
    for (let i = 0; i < data.length; i += 40) {
      brightness += (data[i] + data[i+1] + data[i+2]) / 3;
    }
    brightness /= (data.length / 40);
    
    // Very basic dummy response if websocket not connected
    postMessage({
      type: 'frame_result',
      result: {
        hasFace: brightness > 20,
        focusScore: 0.5,
        engagementScore: 0.5,
        presence: 'unknown',
        isDistracted: false
      }
    } as CVWorkerResult);
    return;
  }
  
  if (typeof OffscreenCanvas !== 'undefined') {
    const canvas = new OffscreenCanvas(imageData.width, imageData.height);
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.putImageData(imageData, 0, 0);
      canvas.convertToBlob({ type: 'image/jpeg', quality: 0.7 })
        .then(blob => {
          const reader = new FileReader();
          reader.readAsDataURL(blob); 
          reader.onloadend = function() {
            const base64data = reader.result as string;
            ws?.send(JSON.stringify({ image: base64data.split(',')[1] }));
          }
        });
    }
  } else {
    // Fallback: Send raw metadata if no OffscreenCanvas
    ws.send(JSON.stringify({ 
      event: "frame_data_raw",
      width: imageData.width,
      height: imageData.height,
      timestamp: Date.now()
    }));
  }
}

self.onmessage = (event: MessageEvent<CVWorkerMessage>) => {
  const data = event.data;
  
  if (data.type === 'init') {
    if (data.backendUrl && data.sessionId) {
      currentSessionId = data.sessionId;
      connectWebSocket(data.backendUrl, data.sessionId);
    } else {
      postMessage({ type: 'error', error: 'Missing backendUrl or sessionId' } as CVWorkerResult);
    }
  } else if (data.type === 'process_frame') {
    if (data.imageData) {
      processFrame(data.imageData);
    }
  } else if (data.type === 'stop') {
    if (ws) {
      ws.close();
      ws = null;
    }
  }
};

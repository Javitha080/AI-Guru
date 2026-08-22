export interface FrameSamplerOptions {
  targetFPS: number;
  maxFPS: number;
  onFrame: (imageData: ImageData, timestamp: number) => void;
}

export class FrameSampler {
  private videoElement: HTMLVideoElement | null = null;
  private canvas: OffscreenCanvas | null = null;
  private ctx: OffscreenCanvasRenderingContext2D | null = null;
  private animationId: number | null = null;
  private lastFrameTime: number = 0;
  private running: boolean = false;
  private options: FrameSamplerOptions;

  constructor(options: FrameSamplerOptions) {
    this.options = {
      targetFPS: options.targetFPS || 5,
      maxFPS: options.maxFPS || 10,
      onFrame: options.onFrame
    };
  }

  attach(video: HTMLVideoElement): void {
    this.videoElement = video;
    if (typeof OffscreenCanvas !== 'undefined') {
      this.canvas = new OffscreenCanvas(video.videoWidth || 640, video.videoHeight || 480);
      this.ctx = this.canvas.getContext('2d', { willReadFrequently: true }) as OffscreenCanvasRenderingContext2D;
    } else {
      // Fallback for browsers that do not support OffscreenCanvas
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      this.canvas = canvas as any;
      this.ctx = canvas.getContext('2d', { willReadFrequently: true }) as any;
    }
  }

  start(): void {
    if (!this.videoElement || this.running) return;
    this.running = true;
    this.lastFrameTime = performance.now();
    this.loop(this.lastFrameTime);
  }

  stop(): void {
    this.running = false;
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  setTargetFPS(fps: number): void {
    this.options.targetFPS = Math.min(Math.max(1, fps), this.options.maxFPS);
  }

  destroy(): void {
    this.stop();
    this.videoElement = null;
    this.canvas = null;
    this.ctx = null;
  }

  private loop(timestamp: number): void {
    if (!this.running) return;

    this.animationId = requestAnimationFrame((t) => this.loop(t));

    const elapsed = timestamp - this.lastFrameTime;
    const frameInterval = 1000 / this.options.targetFPS;

    if (elapsed > frameInterval) {
      this.lastFrameTime = timestamp - (elapsed % frameInterval);
      this.captureFrame(timestamp);
    }
  }

  private captureFrame(timestamp: number): void {
    if (!this.videoElement || !this.ctx || !this.canvas) return;
    
    // Update canvas size if video size changed
    if (this.canvas.width !== this.videoElement.videoWidth || this.canvas.height !== this.videoElement.videoHeight) {
      this.canvas.width = this.videoElement.videoWidth || 640;
      this.canvas.height = this.videoElement.videoHeight || 480;
    }
    
    if (this.videoElement.readyState >= 2) {
      this.ctx.drawImage(this.videoElement, 0, 0, this.canvas.width, this.canvas.height);
      const imageData = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
      this.options.onFrame(imageData, timestamp);
    }
  }
}

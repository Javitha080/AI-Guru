// Minimal ambient types for the Document Picture-in-Picture API
// (Chromium-only; feature-detected at runtime via `"documentPictureInPicture" in window`).

interface DocumentPictureInPictureOptions {
  width?: number;
  height?: number;
  preferInitialWindowPlacement?: boolean;
}

interface DocumentPictureInPicture {
  /** The PiP window, or null while closed. */
  readonly window: Window | null;
  requestWindow(options?: DocumentPictureInPictureOptions): Promise<Window>;
}

interface Window {
  documentPictureInPicture?: DocumentPictureInPicture;
}

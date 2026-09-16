declare module "lenis" {
  export default class Lenis {
    constructor(options?: Record<string, unknown>);
    raf(time: number): void;
    destroy(): void;
    on(event: string, callback: (...args: unknown[]) => void): void;
    off(event: string, callback: (...args: unknown[]) => void): void;
    scrollTo(target: unknown, options?: Record<string, unknown>): void;
  }
}

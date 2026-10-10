declare module '@novnc/novnc/lib/rfb' {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: { shared?: boolean; credentials?: Record<string, string>; wsProtocols?: string[] })
    viewOnly: boolean
    scaleViewport: boolean
    resizeSession: boolean
    background: string
    disconnect(): void
  }
}

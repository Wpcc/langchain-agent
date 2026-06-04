export class ChatWebSocket {
  private ws: WebSocket | null = null

  constructor(
    private readonly convId: string,
    private readonly token: string,
  ) {}

  connect(
    onChunk: (chunk: string) => void,
    onEnd: () => void,
    onError: (msg: string) => void,
  ) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/api/chat/ws/${this.convId}?token=${this.token}`
    this.ws = new WebSocket(url)

    this.ws.onmessage = ({ data }: MessageEvent<string>) => {
      if (data === '__END__') {
        onEnd()
      } else if (data.startsWith('__ERROR__:')) {
        onError(data.replace('__ERROR__:', ''))
      } else {
        onChunk(data)
      }
    }

    this.ws.onerror = () => onError('WebSocket 连接失败，请刷新页面重试')
  }

  send(message: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(message)
    }
  }

  close() {
    this.ws?.close()
    this.ws = null
  }
}

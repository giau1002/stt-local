export class Capture {
  private context?: AudioContext
  private stream?: MediaStream
  private worklet?: AudioWorkletNode
  private flushed?: ()=>void
  private stopping?: Promise<void>
  async prepare() {
    if(!window.isSecureContext) throw new Error('Microphone cần HTTPS hoặc localhost. Xem hướng dẫn cấu hình TLS.')
    this.context=new AudioContext({sampleRate:16000});await this.context.resume()
    this.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false}})
    await this.context.audioWorklet.addModule('/pcm-worklet.js')
  }
  start(send:(bytes:ArrayBuffer)=>void, level:(n:number)=>void) {
    const context=this.context!
    if(context.sampleRate!==16000) throw new Error('Trình duyệt không hỗ trợ 16 kHz; thử Chrome hoặc Edge.')
    const source=context.createMediaStreamSource(this.stream!)
    this.worklet=new AudioWorkletNode(context,'pcm16-capture')
    this.worklet.port.onmessage=event=>{
      if(event.data.type==='flushed'){this.flushed?.();return}
      const samples=new Int16Array(event.data.bytes);let sum=0
      for(const s of samples)sum+=(s/32768)**2
      level(Math.min(1,Math.sqrt(sum/samples.length)*4));send(event.data.bytes)
    }
    const muted=context.createGain();muted.gain.value=0
    source.connect(this.worklet);this.worklet.connect(muted);muted.connect(context.destination)
  }
  stop():Promise<void> {
    if(this.stopping)return this.stopping
    this.stopping=(async()=>{
      if(this.worklet){
        await new Promise<void>(resolve=>{const timer=setTimeout(resolve,500);this.flushed=()=>{clearTimeout(timer);resolve()};this.worklet!.port.postMessage('flush')})
        this.worklet.disconnect();this.worklet=undefined
      }
      this.stream?.getTracks().forEach(t=>t.stop())
      if(this.context && this.context.state!=='closed')await this.context.close()
    })()
    return this.stopping
  }
}

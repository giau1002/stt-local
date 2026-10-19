<script setup lang="ts">
import {computed,nextTick,onMounted,ref} from 'vue'
import {Capture} from './capture'
type Turn={text:string;start:number;end:number;speaker_id:string|null;overlap:boolean}
type Segment={segment_id:number;text:string;turns:Turn[]}
type Session={id:string;title:string;created_at:string;status:string;duration:number;speakers:Record<string,string>;segments:Segment[]}
type Status={ready:boolean;error:string|null;active_sessions:number;max_sessions:number;diar_device:string}
const authenticated=ref(false),key=ref(''),error=ref(''),busy=ref(false),historyVisible=ref(false)
const status=ref<Status|null>(null),sessions=ref<Session[]>([]),current=ref<Session|null>(null)
const recording=ref(false),stopping=ref(false),seconds=ref(0),level=ref(0),pending=ref(0)
const partials=ref<Record<number,string>>({}),names=ref<Record<string,string>>({}),title=ref('Cuộc trò chuyện mới'),tail=ref<HTMLElement|null>(null)
let capture:Capture|null=null,socket:WebSocket|null=null,sequence=0
const unacked=new Set<number>()
const turns=computed(()=>current.value?.segments.flatMap(s=>s.turns)||[])
const speakers=computed(()=>[...new Set(turns.value.map(t=>t.speaker_id).filter(Boolean))] as string[])
const active=computed(()=>recording.value||stopping.value||busy.value)
const words=computed(()=>turns.value.map(t=>t.text).join(' ').trim().split(/\s+/).filter(Boolean).length)
const time=(s:number)=>`${Math.floor(s/60).toString().padStart(2,'0')}:${Math.floor(s%60).toString().padStart(2,'0')}`
const date=(s:string)=>new Date(s).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
const name=(s:string|null)=>s?(current.value?.speakers[s]||`Người nói ${s.split('_')[1]}`):'Chưa xác định'
const color=(s:string|null)=>s?(Number(s.split('_')[1])-1)%5:5
async function api(path:string,options:RequestInit={}){
  const r=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...options.headers}})
  if(!r.ok){if(r.status===401)authenticated.value=false;const b=await r.json().catch(()=>({detail:'Không kết nối được máy chủ'}));throw new Error(typeof b.detail==='string'?b.detail:'Dữ liệu không hợp lệ')}
  return r.json()
}
async function refresh(){status.value=await api('/status');sessions.value=await api('/sessions')}
async function login(){busy.value=true;error.value='';try{await api('/login',{method:'POST',body:JSON.stringify({key:key.value})});key.value='';authenticated.value=true;await refresh()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function open(s:Session){if(active.value)return;try{current.value=await api(`/sessions/${s.id}`);names.value={...current.value!.speakers};partials.value={};seconds.value=current.value!.duration;historyVisible.value=false}catch(e){error.value=(e as Error).message}}
async function rename(s:string){try{const value=(names.value[s]||'').trim();if(!value)return;await api(`/sessions/${current.value!.id}/speakers/${s}`,{method:'PUT',body:JSON.stringify({name:value})});current.value!.speakers[s]=value}catch(e){error.value=(e as Error).message}}
function send(bytes:ArrayBuffer){
  if(!socket||socket.readyState!==WebSocket.OPEN)return
  if(unacked.size>=50||socket.bufferedAmount>192000){error.value='Máy chủ xử lý chậm. Đã dừng thu; phần âm thanh chưa gửi không có trong bản ghi.';void stop();return}
  const packet=new ArrayBuffer(4+bytes.byteLength);new DataView(packet).setUint32(0,sequence,true);new Uint8Array(packet,4).set(new Uint8Array(bytes))
  unacked.add(sequence++);pending.value=unacked.size;socket.send(packet)
}
async function start(){
  busy.value=true;error.value='';partials.value={};unacked.clear();pending.value=0;sequence=0
  try{
    capture=new Capture();await capture.prepare()
    socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/stream`)
    await new Promise<void>((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Máy chủ chưa phản hồi')),15000)
      socket!.onopen=()=>socket!.send(JSON.stringify({type:'start',sample_rate:16000,encoding:'pcm_s16le',title:title.value}))
      socket!.onerror=()=>{clearTimeout(timer);reject(new Error('Không mở được kết nối âm thanh'))}
      socket!.onmessage=async event=>{
        const data=JSON.parse(event.data)
        if(data.type==='started'){clearTimeout(timer);current.value={id:data.session_id,title:title.value,created_at:new Date().toISOString(),status:'recording',duration:0,speakers:{},segments:[]};names.value={};seconds.value=0;recording.value=true;resolve()}
        else if(data.type==='partial')partials.value[data.segment_id]=data.text
        else if(data.type==='final'){if(!current.value!.segments.some(s=>s.segment_id===data.segment_id))current.value!.segments.push(data);delete partials.value[data.segment_id]}
        else if(data.type==='ack'){unacked.delete(data.seq);pending.value=unacked.size;seconds.value=data.audio_seconds??seconds.value}
        else if(data.type==='done'){recording.value=false;stopping.value=false;level.value=0;partials.value={};current.value!.status=data.status;current.value!.duration=data.audio_seconds;seconds.value=data.audio_seconds;await refresh().catch(e=>error.value=e.message)}
        else if(data.type==='error'){clearTimeout(timer);error.value=data.message;reject(new Error(data.message));void stop()}
        await nextTick();tail.value?.scrollIntoView({behavior:'smooth',block:'nearest'})
      }
      socket!.onclose=()=>{clearTimeout(timer);if(recording.value||stopping.value){error.value||='Kết nối đã ngắt. Mở lại phiên để xem các đoạn máy chủ đã lưu.';recording.value=false;stopping.value=false;void capture?.stop();level.value=0;void refresh().catch(()=>{})}reject(new Error('Kết nối đã đóng'))}
    })
    capture.start(send,n=>level.value=n)
  }catch(e){error.value=(e as Error).message;await capture?.stop();socket?.close();recording.value=false;stopping.value=false}finally{busy.value=false}
}
async function stop(){if(stopping.value)return;stopping.value=true;await capture?.stop();recording.value=false;level.value=0;if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'end'}));else stopping.value=false}
function fresh(){if(active.value)return;current.value=null;partials.value={};seconds.value=0;error.value='';historyVisible.value=false}
function exportFile(e:Event){const s=e.target as HTMLSelectElement;if(s.value&&current.value)window.open(`/api/sessions/${current.value.id}/export/${s.value}`,'_blank');s.value=''}
async function logout(){await api('/logout',{method:'POST'});authenticated.value=false;current.value=null;sessions.value=[]}
onMounted(async()=>{try{await refresh();authenticated.value=true}catch{/* Login is expected. */}})
</script>
<template>
  <div v-if="!authenticated" class="login-shell">
    <section class="login-story"><div class="brand"><b>v.</b> VietVoice</div><p class="eyebrow">KHÔNG GIAN RIÊNG CHO GIỌNG NÓI</p><h1>Tập trung trò chuyện.<br>Để lời nói được ghi lại.</h1><p>Chuyển giọng nói tiếng Việt thành văn bản và phân biệt người nói, ngay trên máy chủ của bạn.</p><div class="sound-art" aria-hidden="true"><i v-for="n in 32" :key="n" :style="{height:`${22+Math.sin(n*.7)**2*100}px`}"></i></div><small>Tiếng Việt · Xử lý tại chỗ · Không dùng API đám mây</small></section>
    <form class="login-card" @submit.prevent="login"><span class="eyebrow">VIETVOICE LOCAL / 0.1</span><h2>Chào mừng trở lại</h2><p>Nhập mã truy cập của máy chủ để bắt đầu.</p><label for="key">Mã truy cập</label><input id="key" v-model="key" type="password" autocomplete="current-password" required placeholder="Mã do quản trị viên cấp"><div v-if="error" role="alert" class="error">{{error}}</div><button class="primary" :disabled="busy">{{busy?'Đang kết nối…':'Mở không gian làm việc →'}}</button><small>Âm thanh được xử lý trên máy chủ đã cấu hình. Bản ghi chỉ hiển thị sau khi đăng nhập.</small></form>
  </div>
  <div v-else class="workspace">
    <aside class="sidebar" :class="{show:historyVisible}"><div class="brand"><b>v.</b> VietVoice <small>LOCAL</small></div><button class="new-button" @click="fresh" :disabled="active">+ <span>Phiên ghi mới</span></button><div class="side-label">BẢN GHI GẦN ĐÂY <span>{{sessions.length}}</span></div><nav class="session-list" aria-label="Các phiên ghi"><button v-for="s in sessions" :key="s.id" @click="open(s)" :disabled="active" :class="{selected:current?.id===s.id}"><span class="session-icon">≋</span><span><strong>{{s.title}}</strong><small>{{date(s.created_at)}} · {{time(s.duration)}}</small></span></button><p v-if="!sessions.length" class="side-empty">Các cuộc trò chuyện đã lưu sẽ xuất hiện tại đây.</p></nav><div class="side-foot"><span class="dot"></span> Máy chủ riêng<button @click="logout" :disabled="active" title="Đăng xuất">↪</button></div></aside>
    <main><header class="topbar"><button class="mobile-menu" @click="historyVisible=!historyVisible" aria-label="Mở danh sách phiên">☰</button><span>Không gian làm việc <em>/ Bản ghi</em></span><span class="status-pill" :class="{warning:!status?.ready}"><i></i>{{status?.ready?'AI đã sẵn sàng':'Chưa nạp model'}}</span></header>
      <div class="content"><div class="heading"><div><div class="eyebrow">GHI ÂM & CHUYỂN THÀNH VĂN BẢN</div><h1>{{current?.title || 'Lắng nghe. Ghi lại. Hiểu rõ.'}}</h1><p>Giữ trọn cuộc trò chuyện, rõ lời từng người.</p></div><select v-if="current" aria-label="Xuất bản ghi" @change="exportFile"><option value="">Tải xuống ↓</option><option value="txt">Văn bản .txt</option><option value="json">Dữ liệu .json</option><option value="srt">Phụ đề .srt</option></select></div>
        <div v-if="error" role="alert" class="error">{{error}}<button @click="error=''" aria-label="Ẩn thông báo">×</button></div>
        <div v-if="!status?.ready" class="notice"><strong>Máy chủ chưa sẵn sàng nhận âm thanh</strong><p>{{status?.error || 'Đang kiểm tra model…'}}</p><button @click="refresh">Kiểm tra lại</button></div>
        <div class="studio"><section class="transcript-card"><header class="card-head"><div class="tabs"><span>Bản hội thoại</span><small>{{words}} từ</small></div><span class="live-label" :class="{live:recording}"><i></i>{{recording?'Đang ghi trực tiếp':stopping?'Đang chốt…':current?'Đã lưu':'Sẵn sàng'}}</span></header>
          <div class="transcript-body" aria-live="polite"><div v-if="!turns.length && !Object.values(partials).some(Boolean)" class="empty"><div class="empty-mic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg></div><h2>{{recording?'Đang lắng nghe bạn…':'Cuộc trò chuyện bắt đầu ở đây'}}</h2><p>{{recording?'Văn bản sẽ xuất hiện khi nhận được lời nói.':'Bật microphone để nhận văn bản trực tiếp. Hệ thống tự phân biệt tối đa 8 người nói trong một phiên.'}}</p><div class="tags"><span>Tiếng Việt</span><span>Phân biệt người nói</span><span>Lưu tại máy chủ</span></div></div>
            <article v-for="(turn,i) in turns" :key="i" class="turn"><div class="avatar" :class="`speaker-${color(turn.speaker_id)}`">{{turn.speaker_id?.split('_')[1] || '?'}}</div><div class="turn-content"><div class="turn-label"><strong>{{name(turn.speaker_id)}}</strong><time>{{time(turn.start)}}</time><span v-if="turn.overlap" class="overlap">Nói chồng nhau</span></div><p>{{turn.text}}</p></div></article>
            <article v-for="(text,id) in partials" :key="id" v-show="text" class="turn draft"><div class="avatar">···</div><div class="turn-content"><div class="turn-label"><strong>Đang nhận dạng</strong><span>Bản nháp</span></div><p>{{text}}</p></div></article><div ref="tail"></div>
          </div><footer class="transcript-foot"><span>Bản nháp có thể thay đổi trước khi chốt.</span><span>{{current?.status==='interrupted'?'Phiên gián đoạn':current?.status==='failed'?'Lỗi xử lý':`${turns.length} lượt lời`}}</span></footer></section>
          <aside class="details"><section><div class="section-title">NGƯỜI NÓI <span>{{speakers.length}} / 8</span></div><p v-if="!speakers.length" class="muted">Người nói được thêm tự động khi đủ âm thanh để phân biệt.</p><div v-for="s in speakers" :key="s" class="speaker-edit"><span class="avatar" :class="`speaker-${color(s)}`">{{s.split('_')[1]}}</span><input v-model="names[s]" :placeholder="name(s)" :aria-label="`Tên ${name(s)}`" maxlength="80" @change="rename(s)"></div><small v-if="speakers.length">Nhập tên để đổi cách hiển thị trong phiên này.</small></section><section><div class="section-title">PHIÊN LÀM VIỆC</div><dl><div><dt>Ngôn ngữ</dt><dd>Tiếng Việt</dd></div><div><dt>Thời lượng</dt><dd>{{time(seconds)}}</dd></div><div><dt>Chưa xác nhận</dt><dd>{{pending}} gói</dd></div><div><dt>Người nói</dt><dd>Tự động</dd></div></dl></section><section class="privacy-note"><span>◇</span><strong>Xử lý trong hệ thống riêng</strong><p>Không gửi âm thanh đến dịch vụ nhận dạng bên ngoài. Bản này lưu văn bản, không lưu file ghi âm.</p></section><small>Khi nói chồng hoặc thiếu dữ liệu, nhãn có thể là “Chưa xác định”.</small></aside>
        </div>
        <div class="recorder"><div class="record-info"><span class="record-dot" :class="{pulsing:recording}"></span><div><strong>{{recording?'Microphone đang bật':stopping?'Đang xử lý phần cuối':'Microphone'}}</strong><small>{{recording?'Nói tự nhiên, từng người một':'Âm thanh mono · 16 kHz'}}</small></div></div><div class="meter" aria-label="Mức âm thanh"><i v-for="n in 24" :key="n" :class="{lit:n/24<=level}" :style="{height:`${8+(n%5)*4}px`}"></i></div><time class="timer">{{time(seconds)}}</time><button v-if="recording||stopping" class="stop-button" @click="stop" :disabled="stopping">■ {{stopping?'Đang chốt…':'Dừng & lưu'}}</button><button v-else class="primary" @click="start" :disabled="!status?.ready||busy">● {{busy?'Đang kết nối…':'Bắt đầu ghi'}}</button></div>
        <div v-if="!active" class="session-title"><label for="title">Tên phiên mới</label><input id="title" v-model="title" maxlength="120"></div><div class="bottom-note">VietVoice Local <span>Zipformer + Nemotron · Bản triển khai 0.1</span></div>
      </div>
    </main>
  </div>
</template>

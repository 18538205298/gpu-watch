<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { log, logs, overview, type LogFile, type Snapshot } from './api'

const snapshot = ref<Snapshot>({ ok:false, gpus:[], apps:[], processes:[] })
const files = ref<LogFile[]>([])
const selected = ref('')
const content = ref('')
const error = ref('')
const selectedMeta = ref<{ mtime_iso?: string; age_seconds?: number; read_at?: number }>({})
let timer: number | undefined
let logTimer: number | undefined

async function refresh() {
  try { snapshot.value = await overview(); const result = await logs(); files.value = result.files || []; if (!selected.value && files.value.length) selected.value = files.value[0].path; if (selected.value) await refreshLog() }
  catch (e:any) { error.value = e?.message || '连接失败' }
}
async function refreshLog() { if (!selected.value) return; const result = await log(selected.value); content.value = result.content || ''; selectedMeta.value = { mtime_iso: result.mtime_iso, age_seconds: result.age_seconds, read_at: result.read_at }; if (result.error) error.value = result.error }
function formatSize(n:number) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(1)} KB` : `${(n/1048576).toFixed(1)} MB` }
function selectFile(path:string) { selected.value = path; void refreshLog() }
onMounted(() => { void refresh(); timer = window.setInterval(refresh, 3000); logTimer = window.setInterval(refreshLog, 1000) })
onUnmounted(() => { if (timer) clearInterval(timer); if (logTimer) clearInterval(logTimer) })
</script>

<template>
  <main class="page">
    <header><div><h1>GPU Watch</h1><p>远程 GPU 实例 · 命令与实时日志</p></div><span :class="['state', snapshot.ok ? 'on' : 'off']">{{ snapshot.ok ? '已连接' : '未连接' }}</span></header>
    <section class="gpu-grid">
      <article v-for="gpu in snapshot.gpus" :key="gpu.index" class="card"><b>GPU {{ gpu.index }} · {{ gpu.name }}</b><div class="metrics"><span>利用率 <strong>{{ gpu.utilization }}%</strong></span><span>显存 <strong>{{ gpu.memory_used }} / {{ gpu.memory_total }} MB</strong></span><span>温度 <strong>{{ gpu.temperature }}°C</strong></span></div></article>
      <article v-if="!snapshot.gpus.length" class="card muted">{{ snapshot.error || '没有 GPU 数据' }}</article>
    </section>
    <section class="layout">
      <aside class="panel"><div class="panel-title">GPU 进程</div><div v-if="snapshot.apps.length" v-for="app in snapshot.apps" :key="app.pid" class="process"><b>{{ app.pid }}</b><span>{{ app.name }}</span><em>{{ app.memory }} MiB</em></div><div v-else class="muted">暂无计算进程</div><div class="panel-title command-title">全部进程命令</div><div v-for="process in snapshot.processes" :key="`${process.pid}-${process.command}`" class="command"><span class="pid">{{ process.pid }}</span><code>{{ process.command }}</code></div></aside>
      <section class="panel logs"><div class="panel-title">日志尾部（每秒刷新） <select v-model="selected" @change="refreshLog"><option value="">选择日志</option><option v-for="file in files" :key="file.path" :value="file.path">{{ file.path }} · {{ file.mtime_iso || '无时间' }} · {{ file.age_seconds !== undefined ? `${Math.round(file.age_seconds)}秒前` : '' }}</option></select></div><div v-if="selected" class="log-meta">文件最后修改：{{ selectedMeta.mtime_iso || '未知' }} · 距现在 {{ selectedMeta.age_seconds !== undefined ? `${Math.round(selectedMeta.age_seconds)}秒` : '未知' }} · 本次读取：{{ selectedMeta.read_at ? new Date(selectedMeta.read_at * 1000).toLocaleTimeString() : '—' }}</div><pre>{{ content || '选择一个日志文件' }}</pre></section>
    </section>
    <p v-if="error" class="error">{{ error }}</p>
  </main>
</template>
